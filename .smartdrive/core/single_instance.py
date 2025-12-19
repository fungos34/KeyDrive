# core/single_instance.py - Per-drive single instance management
"""
Cross-platform single-instance-per-drive implementation.

Uses QLocalServer/QLocalSocket for IPC when Qt is available,
with filesystem lock fallback for robustness.

Per AGENT_ARCHITECTURE.md Section 2.5:
- Cross-platform: Windows, Linux, macOS
- Deterministic: no race conditions
- Clean release on exit/crash

Protocol:
- Server name: "KeyDrive.instance.{drive_id}" (sanitized)
- IPC messages: JSON with version header
- Commands: ACTIVATE, PING
"""

import hashlib
import json
import logging
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

# Logger for single instance operations
_instance_logger = logging.getLogger('SmartDrive.instance')


# =============================================================================
# IPC Protocol Constants
# =============================================================================

# Protocol version for forward compatibility
IPC_PROTOCOL_VERSION = 1

# IPC Commands
IPC_CMD_ACTIVATE = "ACTIVATE"
IPC_CMD_PING = "PING"

# IPC Response
IPC_RESP_OK = "OK"
IPC_RESP_ERROR = "ERROR"

# Server name prefix (app namespace)
SERVER_NAME_PREFIX = "KeyDrive.instance"


# =============================================================================
# Server Name Generation
# =============================================================================

def sanitize_server_name(drive_id: str) -> str:
    """
    Generate a sanitized server name from drive_id.
    
    Requirements:
    - Unique per drive_id
    - Valid on all platforms (Windows, Linux, macOS)
    - Length-limited for platform constraints
    
    Args:
        drive_id: UUIDv4 drive identifier
        
    Returns:
        Sanitized server name string
    """
    # Use hash to ensure consistent length and valid characters
    # MD5 is fine here - not for security, just uniqueness/sanitization
    hash_suffix = hashlib.md5(drive_id.encode('utf-8')).hexdigest()[:16]
    
    # Format: KeyDrive.instance.{hash}
    # Max ~30 chars, safe for all platforms
    server_name = f"{SERVER_NAME_PREFIX}.{hash_suffix}"
    
    return server_name


def get_lock_file_path(drive_id: str) -> Path:
    """
    Get platform-appropriate lock file path for drive_id.
    
    Args:
        drive_id: UUIDv4 drive identifier
        
    Returns:
        Path to lock file
    """
    server_name = sanitize_server_name(drive_id)
    
    system = platform.system().lower()
    
    if system == 'windows':
        # Windows: use temp directory
        temp_dir = Path(tempfile.gettempdir())
        return temp_dir / f"{server_name}.lock"
    elif system == 'darwin':
        # macOS: use /tmp or user temp
        return Path('/tmp') / f"{server_name}.lock"
    else:
        # Linux/Unix: use /tmp with XDG fallback
        xdg_runtime = os.environ.get('XDG_RUNTIME_DIR')
        if xdg_runtime:
            return Path(xdg_runtime) / f"{server_name}.lock"
        return Path('/tmp') / f"{server_name}.lock"


# =============================================================================
# IPC Message Handling
# =============================================================================

def create_ipc_message(command: str, **kwargs) -> bytes:
    """
    Create an IPC message.
    
    Args:
        command: IPC command (ACTIVATE, PING, etc.)
        **kwargs: Additional message fields
        
    Returns:
        JSON-encoded message bytes
    """
    message = {
        "version": IPC_PROTOCOL_VERSION,
        "command": command,
        **kwargs
    }
    return json.dumps(message).encode('utf-8')


def parse_ipc_message(data: bytes) -> Optional[dict]:
    """
    Parse an IPC message.
    
    Args:
        data: Raw message bytes
        
    Returns:
        Parsed message dict or None if invalid
    """
    try:
        message = json.loads(data.decode('utf-8'))
        if not isinstance(message, dict):
            return None
        if 'version' not in message or 'command' not in message:
            return None
        return message
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# =============================================================================
# Single Instance Manager (Qt-based)
# =============================================================================

class SingleInstanceManager:
    """
    Manages single-instance-per-drive enforcement.
    
    Uses QLocalServer for IPC when Qt is available.
    Implements filesystem locking as additional safeguard.
    
    Usage:
        manager = SingleInstanceManager(drive_id, on_activate_callback)
        
        if not manager.try_acquire():
            # Another instance is running
            manager.send_activate()
            sys.exit(0)
        
        # We are the owner
        manager.start_server()
        # ... run app ...
        manager.release()
    """
    
    def __init__(self, drive_id: str, on_activate: Optional[Callable[[], None]] = None):
        """
        Initialize single instance manager.
        
        Args:
            drive_id: UUIDv4 drive identifier
            on_activate: Callback when ACTIVATE message received (show/focus window)
        """
        self.drive_id = drive_id
        self.server_name = sanitize_server_name(drive_id)
        self.lock_file_path = get_lock_file_path(drive_id)
        self.on_activate = on_activate
        
        self._lock_file = None
        self._server = None
        self._is_owner = False
        
        _instance_logger.info(f"SingleInstanceManager initialized for drive_id={drive_id[:8]}...")
        _instance_logger.debug(f"Server name: {self.server_name}")
        _instance_logger.debug(f"Lock file: {self.lock_file_path}")
    
    def try_acquire(self) -> bool:
        """
        Attempt to acquire instance ownership for this drive.
        
        Returns:
            True if we are now the owner, False if another instance owns it
        """
        # First, try to connect to existing server
        if self._try_connect_existing():
            _instance_logger.info("Another instance is running (server responded)")
            return False
        
        # Try to acquire filesystem lock
        if not self._acquire_file_lock():
            _instance_logger.info("Another instance is running (file lock held)")
            return False
        
        self._is_owner = True
        _instance_logger.info("Acquired instance ownership")
        return True
    
    def _try_connect_existing(self) -> bool:
        """
        Try to connect to an existing instance's server.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            from PyQt6.QtNetwork import QLocalSocket
            from PyQt6.QtCore import QCoreApplication
            
            # Need an event loop for Qt networking
            if QCoreApplication.instance() is None:
                # Create temporary app for connection attempt
                temp_app = QCoreApplication(sys.argv)
            
            socket = QLocalSocket()
            socket.connectToServer(self.server_name)
            
            # Wait up to 1 second for connection
            if socket.waitForConnected(1000):
                # Send ping to verify server is responsive
                socket.write(create_ipc_message(IPC_CMD_PING))
                socket.waitForBytesWritten(500)
                
                if socket.waitForReadyRead(500):
                    response = parse_ipc_message(socket.readAll().data())
                    socket.disconnectFromServer()
                    return response is not None
                
                socket.disconnectFromServer()
                return True  # Connected but no response - assume alive
            
            return False
            
        except ImportError:
            _instance_logger.debug("PyQt6 not available, skipping server check")
            return False
        except Exception as e:
            _instance_logger.debug(f"Server connection failed: {e}")
            return False
    
    def _acquire_file_lock(self) -> bool:
        """
        Acquire filesystem lock.
        
        Uses platform-appropriate locking mechanism.
        
        Returns:
            True if lock acquired, False if already held
        """
        try:
            # Ensure parent directory exists
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Open lock file
            self._lock_file = open(self.lock_file_path, 'w')
            
            system = platform.system().lower()
            
            if system == 'windows':
                # Windows: use msvcrt locking
                import msvcrt
                try:
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    return True
                except IOError:
                    self._lock_file.close()
                    self._lock_file = None
                    return False
            else:
                # Unix: use fcntl locking
                import fcntl
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except IOError:
                    self._lock_file.close()
                    self._lock_file = None
                    return False
                    
        except Exception as e:
            _instance_logger.warning(f"File lock acquisition failed: {e}")
            if self._lock_file:
                self._lock_file.close()
                self._lock_file = None
            return False
    
    def start_server(self) -> bool:
        """
        Start IPC server for receiving commands from other instances.
        
        Must be called after try_acquire() returns True.
        
        Returns:
            True if server started, False on error
        """
        if not self._is_owner:
            _instance_logger.error("Cannot start server: not owner")
            return False
        
        try:
            from PyQt6.QtNetwork import QLocalServer
            
            # Remove any stale socket file
            QLocalServer.removeServer(self.server_name)
            
            self._server = QLocalServer()
            self._server.newConnection.connect(self._handle_connection)
            
            if self._server.listen(self.server_name):
                _instance_logger.info(f"IPC server listening on {self.server_name}")
                return True
            else:
                _instance_logger.error(f"Failed to start server: {self._server.errorString()}")
                return False
                
        except ImportError:
            _instance_logger.warning("PyQt6 not available, IPC server disabled")
            return False
        except Exception as e:
            _instance_logger.error(f"Server start failed: {e}")
            return False
    
    def _handle_connection(self) -> None:
        """Handle incoming IPC connection."""
        if not self._server:
            return
        
        socket = self._server.nextPendingConnection()
        if not socket:
            return
        
        # Read message
        if socket.waitForReadyRead(1000):
            data = socket.readAll().data()
            message = parse_ipc_message(data)
            
            if message:
                self._process_message(message, socket)
            else:
                socket.write(create_ipc_message(IPC_RESP_ERROR, reason="Invalid message"))
        
        socket.disconnectFromServer()
    
    def _process_message(self, message: dict, socket) -> None:
        """
        Process received IPC message.
        
        Args:
            message: Parsed message dict
            socket: QLocalSocket to send response
        """
        command = message.get('command')
        
        _instance_logger.info(f"IPC received: {command}")
        
        if command == IPC_CMD_PING:
            socket.write(create_ipc_message(IPC_RESP_OK))
            socket.waitForBytesWritten(500)
            
        elif command == IPC_CMD_ACTIVATE:
            # Trigger activate callback (show/focus window)
            if self.on_activate:
                _instance_logger.info("Activating window via IPC")
                self.on_activate()
            socket.write(create_ipc_message(IPC_RESP_OK))
            socket.waitForBytesWritten(500)
            
        else:
            _instance_logger.warning(f"Unknown IPC command: {command}")
            socket.write(create_ipc_message(IPC_RESP_ERROR, reason="Unknown command"))
            socket.waitForBytesWritten(500)
    
    def send_activate(self) -> bool:
        """
        Send ACTIVATE command to existing instance.
        
        Call this when try_acquire() returns False to activate the existing instance.
        
        Returns:
            True if message sent and acknowledged, False otherwise
        """
        try:
            from PyQt6.QtNetwork import QLocalSocket
            from PyQt6.QtCore import QCoreApplication
            
            # Need an event loop for Qt networking
            if QCoreApplication.instance() is None:
                temp_app = QCoreApplication(sys.argv)
            
            socket = QLocalSocket()
            socket.connectToServer(self.server_name)
            
            if socket.waitForConnected(1000):
                socket.write(create_ipc_message(IPC_CMD_ACTIVATE))
                socket.waitForBytesWritten(500)
                
                if socket.waitForReadyRead(500):
                    response = parse_ipc_message(socket.readAll().data())
                    socket.disconnectFromServer()
                    
                    if response and response.get('command') == IPC_RESP_OK:
                        _instance_logger.info("ACTIVATE sent and acknowledged")
                        return True
                
                socket.disconnectFromServer()
            
            _instance_logger.warning("Failed to send ACTIVATE to existing instance")
            return False
            
        except ImportError:
            _instance_logger.warning("PyQt6 not available, cannot send ACTIVATE")
            return False
        except Exception as e:
            _instance_logger.error(f"ACTIVATE send failed: {e}")
            return False
    
    def release(self) -> None:
        """
        Release instance ownership and cleanup.
        
        Call this on application exit.
        """
        _instance_logger.info("Releasing instance ownership")
        
        # Stop server
        if self._server:
            self._server.close()
            self._server = None
        
        # Release file lock
        if self._lock_file:
            try:
                system = platform.system().lower()
                if system == 'windows':
                    import msvcrt
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            except Exception as e:
                _instance_logger.debug(f"Lock release error: {e}")
            
            self._lock_file.close()
            self._lock_file = None
        
        # Remove lock file
        try:
            if self.lock_file_path.exists():
                self.lock_file_path.unlink()
        except Exception as e:
            _instance_logger.debug(f"Lock file removal failed: {e}")
        
        self._is_owner = False
    
    @property
    def is_owner(self) -> bool:
        """Check if this manager owns the instance lock."""
        return self._is_owner


# =============================================================================
# Convenience Functions
# =============================================================================

def check_single_instance(drive_id: str) -> tuple[bool, Optional[SingleInstanceManager]]:
    """
    Check if this is the only instance for the given drive.
    
    Args:
        drive_id: UUIDv4 drive identifier
        
    Returns:
        Tuple of (is_single_instance, manager_if_owner)
        If is_single_instance is False, manager is None.
    """
    manager = SingleInstanceManager(drive_id)
    
    if manager.try_acquire():
        return True, manager
    else:
        # Try to activate existing instance
        manager.send_activate()
        return False, None
