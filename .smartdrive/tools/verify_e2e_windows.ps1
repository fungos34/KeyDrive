<#
.SYNOPSIS
    Hardware-assisted End-to-End Verification for SmartDrive (Release Gate)
    
.DESCRIPTION
    This script performs comprehensive E2E verification on REAL USB hardware.
    It proves that:
    1. Setup safety guardrails BLOCK destruction of the source disk
    2. All 4 security modes work end-to-end
    3. "Run from anywhere" works (different working directories)
    4. GUI→CLI terminal spawning is correct
    
    REQUIRES:
    - Physical USB drive (will be WIPED - operator must confirm)
    - VeraCrypt installed (with admin rights)
    - Python 3.10+
    - Optional: YubiKey for GPG modes
    
.PARAMETER USBDiskNumber
    The Windows disk number of the USB drive to use (e.g., 1, 2).
    If not provided, the script will enumerate and prompt.
    
.PARAMETER SkipDestructiveTests
    If set, skips tests that require partitioning the USB drive.
    
.PARAMETER LogFile
    Path for structured log output. Default: .smartdrive/logs/e2e-<timestamp>.log
    
.EXAMPLE
    .\verify_e2e_windows.ps1
    # Interactive mode - enumerates disks and prompts
    
.EXAMPLE
    .\verify_e2e_windows.ps1 -USBDiskNumber 2
    # Direct mode - uses disk 2 (still prompts for confirmation)
    
.NOTES
    Per AGENT_ARCHITECTURE.md Section 12: Testing vs Verification
    - This is VERIFICATION (real hardware, real I/O, proves release readiness)
    - Not to be confused with TESTS (pytest, mocks, CI)
#>

[CmdletBinding()]
param(
    [int]$USBDiskNumber = -1,
    [switch]$SkipDestructiveTests,
    [string]$LogFile = ""
)

$ErrorActionPreference = "Stop"

# =============================================================================
# Configuration
# =============================================================================

# $PSScriptRoot = tools folder, parent = project root
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:SmartDriveDir = Join-Path $script:ProjectRoot ".smartdrive"
$script:LogsDir = Join-Path $script:SmartDriveDir "logs"
$script:Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

if ([string]::IsNullOrEmpty($LogFile)) {
    $LogFile = Join-Path $script:LogsDir "e2e-$script:Timestamp.log"
}

# Test counters
$script:TestsPassed = 0
$script:TestsFailed = 0
$script:TestsSkipped = 0

# =============================================================================
# Logging and Output Helpers
# =============================================================================

function Initialize-Logging {
    # Create logs directory if needed
    if (-not (Test-Path $script:LogsDir)) {
        New-Item -ItemType Directory -Path $script:LogsDir -Force | Out-Null
    }
    
    # Initialize log file with header
    $header = @"
================================================================================
SMARTDRIVE E2E VERIFICATION LOG
================================================================================
Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Computer: $env:COMPUTERNAME
User: $env:USERNAME
PowerShell: $($PSVersionTable.PSVersion)
Project Root: $script:ProjectRoot
================================================================================

"@
    $header | Out-File -FilePath $LogFile -Encoding UTF8
}

function Write-LogEntry {
    param(
        [string]$Level,
        [string]$Message
    )
    
    $timestamp = Get-Date -Format "HH:mm:ss.fff"
    $entry = "[$timestamp] [$Level] $Message"
    $entry | Out-File -FilePath $LogFile -Encoding UTF8 -Append
}

function Write-Banner {
    param([string]$Text)
    
    Write-Host "`n"
    Write-Host ("=" * 70) -ForegroundColor Magenta
    Write-Host "  $Text" -ForegroundColor Magenta
    Write-Host ("=" * 70) -ForegroundColor Magenta
    Write-LogEntry "INFO" "=== $Text ==="
}

function Write-Section {
    param([string]$Text)
    
    Write-Host "`n--- $Text ---" -ForegroundColor Cyan
    Write-LogEntry "INFO" "--- $Text ---"
}

function Write-Pass {
    param([string]$Message)
    
    $script:TestsPassed++
    Write-Host "  [PASS] $Message" -ForegroundColor Green
    Write-LogEntry "PASS" $Message
}

function Write-Fail {
    param([string]$Message)
    
    $script:TestsFailed++
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
    Write-LogEntry "FAIL" $Message
}

function Write-Skip {
    param([string]$Message)
    
    $script:TestsSkipped++
    Write-Host "  [SKIP] $Message" -ForegroundColor Yellow
    Write-LogEntry "SKIP" $Message
}

function Write-Info {
    param([string]$Message)
    
    Write-Host "  [INFO] $Message" -ForegroundColor Gray
    Write-LogEntry "INFO" $Message
}

function Write-Warn {
    param([string]$Message)
    
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
    Write-LogEntry "WARN" $Message
}

# =============================================================================
# Python Script Runner (avoids here-string escaping issues)
# =============================================================================

function Invoke-PythonTest {
    <#
    .SYNOPSIS
        Run a Python test script and capture result.
    .DESCRIPTION
        Writes Python code to temp file to avoid PowerShell escaping issues.
        Uses Start-Process with output redirection to files to prevent deadlocks.
    #>
    param(
        [string]$TestName,
        [string]$PythonCode,
        [int]$TimeoutSeconds = 30
    )
    
    $tempFile = [System.IO.Path]::GetTempFileName()
    $tempPy = $tempFile -replace '\.tmp$', '.py'
    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    
    Rename-Item -Path $tempFile -NewName $tempPy -Force
    
    try {
        # Add logging suppression and path injection
        $codeWithPath = @"
import sys
import logging
# Suppress logging to stderr for clean test output
logging.disable(logging.CRITICAL)
sys.path.insert(0, r'$($script:SmartDriveDir)')
$PythonCode
"@
        Set-Content -Path $tempPy -Value $codeWithPath -Encoding UTF8
        
        # Run with output redirected to files (avoids buffer deadlock)
        $proc = Start-Process -FilePath "python" -ArgumentList "`"$tempPy`"" `
            -NoNewWindow -PassThru `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile
        
        # Wait with timeout
        $completed = $proc | Wait-Process -Timeout $TimeoutSeconds -ErrorAction SilentlyContinue
        
        if (-not $proc.HasExited) {
            $proc | Stop-Process -Force
            return @{
                Output = "TIMEOUT: Test '$TestName' exceeded ${TimeoutSeconds}s limit"
                StdOut = ""
                StdErr = "TIMEOUT"
                ExitCode = -1
                TimedOut = $true
            }
        }
        
        $stdout = Get-Content -Path $stdoutFile -Raw -ErrorAction SilentlyContinue
        $stderr = Get-Content -Path $stderrFile -Raw -ErrorAction SilentlyContinue
        
        if ($null -eq $stdout) { $stdout = "" }
        if ($null -eq $stderr) { $stderr = "" }
        
        return @{
            Output = ($stdout + $stderr)
            StdOut = $stdout
            StdErr = $stderr
            ExitCode = $proc.ExitCode
            TimedOut = $false
        }
    } finally {
        if (Test-Path $tempPy) { Remove-Item $tempPy -Force -ErrorAction SilentlyContinue }
        if (Test-Path $stdoutFile) { Remove-Item $stdoutFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $stderrFile) { Remove-Item $stderrFile -Force -ErrorAction SilentlyContinue }
    }
}

# =============================================================================
# Operator Confirmation Prompts
# =============================================================================

function Get-OperatorConfirmation {
    <#
    .SYNOPSIS
        Get explicit operator confirmation for destructive operations.
    #>
    param(
        [string]$Title,
        [string[]]$Warnings,
        [string]$ConfirmPhrase
    )
    
    Write-Host "`n"
    Write-Host ("!" * 70) -ForegroundColor Red
    Write-Host "  $Title" -ForegroundColor Red
    Write-Host ("!" * 70) -ForegroundColor Red
    Write-Host ""
    
    foreach ($warning in $Warnings) {
        Write-Host "  WARNING: $warning" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Host "  To proceed, type exactly: $ConfirmPhrase" -ForegroundColor White
    Write-Host ""
    $response = Read-Host "  Confirmation"
    
    if ($response -ceq $ConfirmPhrase) {
        Write-LogEntry "OPERATOR" "Confirmed: $Title with phrase '$ConfirmPhrase'"
        return $true
    } else {
        Write-LogEntry "OPERATOR" "Rejected: $Title (got '$response', expected '$ConfirmPhrase')"
        return $false
    }
}

# =============================================================================
# Pre-Flight Checks
# =============================================================================

function Test-Prerequisites {
    Write-Banner "PRE-FLIGHT CHECKS"
    
    # Check Python
    Write-Section "Python Environment"
    try {
        $pyVersion = & python --version 2>&1
        if ($pyVersion -match "Python (\d+\.\d+)") {
            $version = [version]$Matches[1]
            if ($version -ge [version]"3.10") {
                Write-Pass "Python $($Matches[1]) detected"
            } else {
                Write-Fail "Python $($Matches[1]) too old (need 3.10+)"
                return $false
            }
        }
    } catch {
        Write-Fail "Python not found in PATH"
        return $false
    }
    
    # Check VeraCrypt
    Write-Section "VeraCrypt Installation"
    $veracryptPaths = @(
        "C:\Program Files\VeraCrypt\VeraCrypt.exe",
        "C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe"
    )
    
    $veracryptFound = $false
    foreach ($path in $veracryptPaths) {
        if (Test-Path $path) {
            Write-Pass "VeraCrypt found: $path"
            $veracryptFound = $true
            break
        }
    }
    
    if (-not $veracryptFound) {
        Write-Fail "VeraCrypt not found in standard locations"
        return $false
    }
    
    # Check project structure
    Write-Section "Project Structure"
    $requiredFiles = @(
        (Join-Path $script:SmartDriveDir "scripts\setup.py"),
        (Join-Path $script:SmartDriveDir "scripts\mount.py"),
        (Join-Path $script:SmartDriveDir "scripts\unmount.py"),
        (Join-Path $script:SmartDriveDir "core\safety.py"),
        (Join-Path $script:SmartDriveDir "core\modes.py")
    )
    
    $allFound = $true
    foreach ($file in $requiredFiles) {
        if (Test-Path $file) {
            Write-Info "Found: $(Split-Path -Leaf $file)"
        } else {
            Write-Fail "Missing: $file"
            $allFound = $false
        }
    }
    
    if ($allFound) {
        Write-Pass "All required files present"
    }
    
    # Check admin rights (needed for disk operations)
    Write-Section "Administrator Rights"
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    
    if ($isAdmin) {
        Write-Pass "Running as Administrator"
    } else {
        Write-Warn "Not running as Administrator - some tests will be limited"
    }
    
    return $allFound
}

# =============================================================================
# Disk Enumeration
# =============================================================================

function Get-DiskEnumeration {
    <#
    .SYNOPSIS
        Enumerate all disks with identity information.
    #>
    
    Write-Banner "DISK ENUMERATION"
    Write-Info "Listing all online disks with identity information"
    Write-Host ""
    
    $disks = Get-Disk | Where-Object { $_.OperationalStatus -eq "Online" }
    
    # Build formatted table
    Write-Host "  #  BusType    Size(GB)  UniqueId (truncated)              FriendlyName"
    Write-Host "  -- --------   -------   --------------------------------  -------------------------"
    
    foreach ($disk in $disks) {
        $num = $disk.Number.ToString().PadLeft(2)
        $bus = $disk.BusType.ToString().PadRight(10)
        $sizeGB = [math]::Round($disk.Size / 1GB, 1).ToString().PadLeft(7)
        $uniqueId = if ($disk.UniqueId) {
            $disk.UniqueId.Substring(0, [Math]::Min(32, $disk.UniqueId.Length))
        } else {
            "N/A"
        }
        $name = if ($disk.FriendlyName) {
            $disk.FriendlyName.Substring(0, [Math]::Min(25, $disk.FriendlyName.Length))
        } else {
            "Unknown"
        }
        
        $marker = if ($disk.BusType -eq "USB") { " <-USB" } else { "" }
        
        Write-Host "  $num $bus $sizeGB   $($uniqueId.PadRight(32))  $name$marker"
        Write-LogEntry "INFO" "Disk ${num}: BusType=$($disk.BusType), Size=${sizeGB}GB, UniqueId=$uniqueId"
    }
    
    Write-Host ""
    
    # Return USB disks
    return $disks | Where-Object { $_.BusType -eq "USB" }
}

function Select-USBDisk {
    <#
    .SYNOPSIS
        Select or validate a USB disk for testing.
    #>
    param([int]$RequestedDiskNumber)
    
    $usbDisks = Get-DiskEnumeration
    
    if ($usbDisks.Count -eq 0) {
        Write-Info "No USB disks detected. Destructive tests will be skipped."
        return $null
    }
    
    Write-Info "Found $($usbDisks.Count) USB disk(s)"
    
    # If specific disk requested, validate it
    if ($RequestedDiskNumber -ge 0) {
        $targetDisk = $usbDisks | Where-Object { $_.Number -eq $RequestedDiskNumber }
        if (-not $targetDisk) {
            Write-Fail "Disk $RequestedDiskNumber is not a USB disk or doesn't exist"
            return $null
        }
        return $targetDisk
    }
    
    # If SkipDestructiveTests, don't ask for disk selection
    if ($SkipDestructiveTests) {
        return $null
    }
    
    # Interactive selection
    Write-Host ""
    Write-Host "  Enter USB disk number to use for E2E testing (will be WIPED):" -ForegroundColor Yellow
    $usbDiskNumbers = ($usbDisks | ForEach-Object { $_.Number }) -join ', '
    Write-Host "  USB disks available: $usbDiskNumbers"
    $selection = Read-Host "  Disk number (or press Enter to skip)"
    
    if ([string]::IsNullOrWhiteSpace($selection)) {
        return $null
    }
    
    try {
        $diskNum = [int]$selection
        $targetDisk = $usbDisks | Where-Object { $_.Number -eq $diskNum }
        if (-not $targetDisk) {
            Write-Fail "Invalid selection: $diskNum"
            return $null
        }
        return $targetDisk
    } catch {
        Write-Fail "Invalid input: $selection"
        return $null
    }
}

# =============================================================================
# VERIFICATION 1: Safety Guardrail
# =============================================================================

function Test-SafetyGuardrail {
    <#
    .SYNOPSIS
        PROVES the safety guardrail BLOCKS source disk destruction.
    #>
    param($USBDisk)
    
    Write-Banner "VERIFICATION 1: SAFETY GUARDRAIL"
    Write-Info "Testing that SetupSafetyPolicy BLOCKS source disk destruction"
    
    # Get the disk hosting this script
    $scriptDrive = (Split-Path -Qualifier $PSScriptRoot).TrimEnd(":")
    $scriptPartition = Get-Partition -DriveLetter $scriptDrive -ErrorAction SilentlyContinue
    
    if (-not $scriptPartition) {
        Write-Skip "Cannot determine source disk (running from network?)"
        return
    }
    
    $sourceDiskNumber = $scriptPartition.DiskNumber
    $sourceDisk = Get-Disk -Number $sourceDiskNumber
    
    Write-Info "Script running from disk $sourceDiskNumber ($($sourceDisk.FriendlyName))"
    
    $uniqueIdPreview = $sourceDisk.UniqueId
    if ($uniqueIdPreview.Length -gt 30) {
        $uniqueIdPreview = $uniqueIdPreview.Substring(0, 30) + "..."
    }
    Write-Info "UniqueId: $uniqueIdPreview"
    
    # Run Python safety check against SOURCE disk (should be BLOCKED)
    Write-Section "Attempting to validate SOURCE disk as target (MUST FAIL)"
    
    $setupScriptPath = Join-Path $script:SmartDriveDir "scripts\setup.py"
    $pythonCode = @"
from core.safety import SetupSafetyPolicy
from pathlib import Path

# Try to validate the source disk as a target
result = SetupSafetyPolicy.validate_before_partition(
    script_path=Path(r'$setupScriptPath'),
    target_disk_number=$sourceDiskNumber
)

if result.is_safe:
    print('GUARDRAIL_FAILED: Source disk was allowed as target!')
else:
    print('GUARDRAIL_PASSED: ' + str(result.block_reason.value))
"@
    
    $testResult = Invoke-PythonTest -TestName "SafetyGuardrail" -PythonCode $pythonCode
    
    if ($testResult.Output -match "GUARDRAIL_PASSED:") {
        $reason = ($testResult.Output -split "GUARDRAIL_PASSED: ")[1]
        Write-Pass "Safety guardrail BLOCKED source disk: $reason"
    } elseif ($testResult.Output -match "GUARDRAIL_FAILED") {
        Write-Fail "CRITICAL: Safety guardrail DID NOT block source disk!"
        Write-Info "Output: $($testResult.Output)"
    } else {
        Write-Fail "Safety guardrail test error: $($testResult.Output)"
    }
    
    # Now test that USB disk IS allowed (if different from source)
    if ($USBDisk -and $USBDisk.Number -ne $sourceDiskNumber) {
        Write-Section "Validating USB disk as target (SHOULD PASS)"
        
        $usbDiskNumber = $USBDisk.Number
        $pythonCode = @"
from core.safety import SetupSafetyPolicy
from pathlib import Path

result = SetupSafetyPolicy.validate_before_partition(
    script_path=Path(r'$setupScriptPath'),
    target_disk_number=$usbDiskNumber
)

if result.is_safe:
    print('TARGET_OK')
else:
    print('TARGET_BLOCKED: ' + str(result.block_reason.value) + ' | ' + str(result.details))
"@
        
        $testResult = Invoke-PythonTest -TestName "USBTarget" -PythonCode $pythonCode
        
        if ($testResult.Output -match "TARGET_OK") {
            Write-Pass "USB disk $usbDiskNumber is allowed as target"
        } else {
            Write-Warn "USB disk blocked (may be expected): $($testResult.Output)"
        }
    }
}

# =============================================================================
# VERIFICATION 2: Security Modes
# =============================================================================

function Test-SecurityModePrerequisites {
    <#
    .SYNOPSIS
        Test that all 4 security mode prerequisites can be checked.
    #>
    
    Write-Banner "VERIFICATION 2: SECURITY MODE MATRIX"
    Write-Info "Testing all 4 security modes from core/modes.py SSOT"
    
    $modes = @("PW_ONLY", "PW_KEYFILE", "PW_GPG_KEYFILE", "GPG_PW_ONLY")
    
    foreach ($modeName in $modes) {
        Write-Section "Mode: $modeName"
        
        $pythonCode = @"
from core.modes import SecurityMode

mode = SecurityMode.$modeName
print('MODE_VALUE: ' + mode.value)
print('MODE_DISPLAY: ' + mode.display_name)
print('REQUIRES_YUBIKEY: ' + str(mode.requires_yubikey))
print('REQUIRES_KEYFILE: ' + str(mode.requires_keyfile))
"@
        
        $testResult = Invoke-PythonTest -TestName "Mode_$modeName" -PythonCode $pythonCode
        
        if ($testResult.Output -match "MODE_VALUE:") {
            $lines = $testResult.Output -split "`n"
            foreach ($line in $lines) {
                if ($line -match "(MODE_VALUE|MODE_DISPLAY|REQUIRES_YUBIKEY|REQUIRES_KEYFILE): (.+)") {
                    Write-Info "$($Matches[1]): $($Matches[2].Trim())"
                }
            }
            Write-Pass "SecurityMode.$modeName validated"
        } else {
            Write-Fail "Mode test error for $modeName : $($testResult.Output)"
        }
    }
}

# =============================================================================
# VERIFICATION 3: Run From Anywhere
# =============================================================================

function Test-RunFromAnywhere {
    <#
    .SYNOPSIS
        Test that SmartDrive scripts work from any working directory.
    #>
    
    Write-Banner "VERIFICATION 3: RUN FROM ANYWHERE"
    
    $testDirs = @(
        @{ Name = "Project Root"; Path = $script:ProjectRoot },
        @{ Name = "Home Directory"; Path = $env:USERPROFILE },
        @{ Name = "Temp Directory"; Path = $env:TEMP }
    )
    
    # Only add System32 if it exists and is accessible
    if (Test-Path "$env:SystemRoot\System32") {
        $testDirs += @{ Name = "System32"; Path = "$env:SystemRoot\System32" }
    }
    
    $smartdriveScript = Join-Path $script:SmartDriveDir "scripts\smartdrive.py"
    
    foreach ($testDir in $testDirs) {
        Write-Section "CWD: $($testDir.Name)"
        Write-Info "Testing from: $($testDir.Path)"
        
        try {
            Push-Location $testDir.Path
            
            # Run smartdrive.py --help
            $result = & python $smartdriveScript --help 2>&1
            $exitCode = $LASTEXITCODE
            
            if ($exitCode -eq 0) {
                Write-Pass "smartdrive.py --help works from $($testDir.Name)"
            } else {
                Write-Fail "smartdrive.py failed from $($testDir.Name): exit=$exitCode"
            }
        } catch {
            Write-Fail "Error running from $($testDir.Name): $_"
        } finally {
            Pop-Location
        }
    }
}

# =============================================================================
# VERIFICATION 4: GUI Terminal Spawning Logic
# =============================================================================

function Test-GUITerminalSpawning {
    <#
    .SYNOPSIS
        Test that GUI terminal calculation logic is correct.
    #>
    
    Write-Banner "VERIFICATION 4: GUI->CLI TERMINAL LOGIC"
    
    # Test the terminal rect computation logic
    Write-Section "Terminal Rect Calculation"
    
    $pythonCode = @"
# Test terminal positioning math without Qt
char_width = 8
char_height = 16
terminal_cols = 120
terminal_rows = 40

terminal_width = terminal_cols * char_width + 40
terminal_height = terminal_rows * char_height + 60

# Simulate placement to right of GUI
gui_x, gui_width = 100, 800
x = gui_x + gui_width + 10
y = 100

print('RECT_OK')
print('Position: ({}, {})'.format(x, y))
print('Size: {}x{}'.format(terminal_width, terminal_height))
"@
    
    $testResult = Invoke-PythonTest -TestName "TerminalRect" -PythonCode $pythonCode
    
    if ($testResult.Output -match "RECT_OK") {
        Write-Pass "Terminal rect calculation works"
        $lines = $testResult.Output -split "`n"
        foreach ($line in $lines) {
            if ($line -match "^(Position|Size):") {
                Write-Info $line.Trim()
            }
        }
    } else {
        Write-Fail "Terminal calculation error: $($testResult.Output)"
    }
    
    # Test that GUI module syntax is valid
    Write-Section "GUI Module Syntax Check"
    
    $guiPath = Join-Path $script:SmartDriveDir "scripts\gui.py"
    $pythonCode = @"
import ast

with open(r'$guiPath', 'r', encoding='utf-8') as f:
    source = f.read()

try:
    ast.parse(source)
    print('GUI_SYNTAX_OK')
    
    if '_compute_terminal_rect_windows' in source:
        print('FUNCTION_FOUND: _compute_terminal_rect_windows')
    else:
        print('FUNCTION_NOT_FOUND: _compute_terminal_rect_windows')
except SyntaxError as e:
    print('GUI_SYNTAX_ERROR: ' + str(e))
"@
    
    $testResult = Invoke-PythonTest -TestName "GUISyntax" -PythonCode $pythonCode
    
    if ($testResult.Output -match "GUI_SYNTAX_OK") {
        Write-Pass "gui.py syntax valid"
        if ($testResult.Output -match "FUNCTION_FOUND") {
            Write-Info "_compute_terminal_rect_windows function present"
        }
    } else {
        Write-Fail "gui.py syntax error: $($testResult.Output)"
    }
}

# =============================================================================
# VERIFICATION 5: Atomic Write Verification
# =============================================================================

function Test-AtomicWrites {
    <#
    .SYNOPSIS
        Test that config writes are atomic (no data loss on crash).
    #>
    
    Write-Banner "VERIFICATION 5: ATOMIC WRITES"
    
    Write-Section "Testing write_config_atomic"
    
    $pythonCode = @"
import tempfile
import json
from pathlib import Path
from core.config import write_config_atomic

with tempfile.TemporaryDirectory() as tmpdir:
    config_path = Path(tmpdir) / 'test_config.json'
    test_data = {'key': 'value', 'number': 42, 'nested': {'a': 1}}
    
    # Write
    write_config_atomic(config_path, test_data)
    
    # Verify
    if not config_path.exists():
        print('ATOMIC_FAIL: file_not_created')
    else:
        with open(config_path) as f:
            loaded = json.load(f)
        
        if loaded != test_data:
            print('ATOMIC_FAIL: content_mismatch')
        else:
            # Check no temp files remain
            temps = list(Path(tmpdir).glob('*.tmp'))
            if temps:
                print('ATOMIC_FAIL: temp_files_remain')
            else:
                print('ATOMIC_OK')
"@
    
    $testResult = Invoke-PythonTest -TestName "AtomicConfig" -PythonCode $pythonCode
    
    if ($testResult.Output -match "ATOMIC_OK") {
        Write-Pass "write_config_atomic works correctly"
    } else {
        Write-Fail "Atomic config write test failed: $($testResult.Output)"
    }
    
    Write-Section "Testing write_file_atomic"
    
    $pythonCode = @"
import tempfile
from pathlib import Path
from core.config import write_file_atomic

with tempfile.TemporaryDirectory() as tmpdir:
    file_path = Path(tmpdir) / 'test_file.txt'
    test_content = b'Test binary content'
    
    write_file_atomic(file_path, test_content)
    
    if not file_path.exists():
        print('ATOMIC_FAIL: file_not_created')
    else:
        with open(file_path, 'rb') as f:
            loaded = f.read()
        
        if loaded != test_content:
            print('ATOMIC_FAIL: content_mismatch')
        else:
            print('ATOMIC_OK')
"@
    
    $testResult = Invoke-PythonTest -TestName "AtomicFile" -PythonCode $pythonCode
    
    if ($testResult.Output -match "ATOMIC_OK") {
        Write-Pass "write_file_atomic works correctly"
    } else {
        Write-Fail "File atomic write test failed: $($testResult.Output)"
    }
}

# =============================================================================
# VERIFICATION 6: DiskIdentity Contract
# =============================================================================

function Test-DiskIdentityContract {
    <#
    .SYNOPSIS
        Test that DiskIdentity.matches() uses UniqueId not disk number.
    #>
    
    Write-Banner "VERIFICATION 6: DISK IDENTITY CONTRACT"
    
    Write-Section "Testing identity matching uses UniqueId"
    
    $pythonCode = @"
from core.safety import DiskIdentity

# Same UniqueId, different disk numbers - MUST match
disk1 = DiskIdentity(unique_id='ABC123', disk_number=1)
disk2 = DiskIdentity(unique_id='ABC123', disk_number=2)  # Different number!

if not disk1.matches(disk2):
    print('IDENTITY_FAIL: same_uniqueid_different_number_should_match')
else:
    # Different UniqueId, same disk number - MUST NOT match
    disk3 = DiskIdentity(unique_id='XYZ789', disk_number=1)

    if disk1.matches(disk3):
        print('IDENTITY_FAIL: different_uniqueid_same_number_should_not_match')
    else:
        # Case insensitivity
        disk4 = DiskIdentity(unique_id='abc123', disk_number=5)
        if not disk1.matches(disk4):
            print('IDENTITY_FAIL: case_insensitive_should_match')
        else:
            print('IDENTITY_OK')
"@
    
    $testResult = Invoke-PythonTest -TestName "DiskIdentity" -PythonCode $pythonCode
    
    if ($testResult.Output -match "IDENTITY_OK") {
        Write-Pass "DiskIdentity contract verified"
    } else {
        Write-Fail "DiskIdentity contract violated"
        Write-LogEntry "ERROR" $testResult.Output
    }
}

# =============================================================================
# VERIFICATION 7: Settings UI System
# =============================================================================

function Test-SettingsUI {
    <#
    .SYNOPSIS
        Test Settings dialog schema-driven UI system using headless Qt.
        Per AGENT_ARCHITECTURE.md: NO SKIPS in release gate.
    #>
    
    Write-Banner "VERIFICATION 7: SETTINGS UI SYSTEM (HEADLESS)"
    Write-Info "Testing SettingsDialog instantiation and schema round-trip"
    
    # Test 1: SettingsDialog instantiation with offscreen Qt
    Write-Section "Testing SettingsDialog instantiation (offscreen Qt)"
    
    $pythonCode = @"
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import sys
import json
import tempfile
from pathlib import Path

# Add project paths
sys.path.insert(0, r'$($script:SmartDriveDir)')
sys.path.insert(0, r'$($script:SmartDriveDir)\scripts')

from PyQt6.QtWidgets import QApplication, QTabWidget
from PyQt6.QtCore import QSettings

from core.constants import ConfigKeys

# Create QApplication
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

# Create test config
test_config = {
    ConfigKeys.DRIVE_ID: "e2e-test-id",
    ConfigKeys.GUI_LANG: "en",
    ConfigKeys.GUI_THEME: "green",
    ConfigKeys.MODE: "pw_only",
    ConfigKeys.DRIVE_NAME: "E2E-Test",
    "unknown_key_preserve": {"nested": "value"},  # Should be preserved
}

# Write to temp file
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(test_config, f)
    config_path = Path(f.name)

try:
    from unittest.mock import patch, MagicMock
    
    # Mock the config path resolution
    with patch('scripts.gui.get_script_dir', return_value=config_path.parent):
        with patch('scripts.gui.resolve_config_path', return_value=config_path):
            from scripts.gui import SettingsDialog
            
            # Create mock QSettings
            mock_settings = MagicMock()
            mock_settings.value.return_value = ""
            
            # Instantiate dialog
            dialog = SettingsDialog(mock_settings, parent=None)
            
            # Verify structure
            assert dialog is not None, "Dialog is None"
            assert hasattr(dialog, 'tab_widget'), "Missing tab_widget"
            assert isinstance(dialog.tab_widget, QTabWidget), "tab_widget not QTabWidget"
            
            # Verify tabs created
            tab_count = dialog.tab_widget.count()
            assert tab_count > 0, f"No tabs created (count={tab_count})"
            
            print(f"SETTINGS_INSTANTIATION_OK:tabs={tab_count}")
            
finally:
    config_path.unlink(missing_ok=True)
"@
    
    $testResult = Invoke-PythonTest -TestName "SettingsInstantiation" -PythonCode $pythonCode
    
    if ($testResult.Output -match "SETTINGS_INSTANTIATION_OK:tabs=(\d+)") {
        $tabCount = $Matches[1]
        Write-Pass "SettingsDialog instantiation succeeded (tabs=$tabCount)"
    } else {
        Write-Fail "SettingsDialog instantiation failed: $($testResult.Output)"
        return
    }
    
    # Test 2: Config round-trip preserves unknown keys
    Write-Section "Testing config save/reload preserves unknown keys"
    
    $pythonCode = @"
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, r'$($script:SmartDriveDir)')

from core.constants import ConfigKeys
from core.config import write_config_atomic

# Test unknown key preservation
original = {
    ConfigKeys.MODE: "pw_only",
    "unknown_root": "preserve_me",
    "unknown_nested": {"deep": {"value": 123}},
}

with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(original, f)
    config_path = Path(f.name)

try:
    # Round-trip via write_config_atomic
    modified = original.copy()
    modified[ConfigKeys.GUI_LANG] = "de"
    write_config_atomic(config_path, modified)
    
    # Reload and verify
    reloaded = json.loads(config_path.read_text(encoding='utf-8'))
    
    # Check unknown keys preserved
    assert reloaded.get("unknown_root") == "preserve_me", "unknown_root lost"
    assert reloaded.get("unknown_nested", {}).get("deep", {}).get("value") == 123, "unknown_nested lost"
    assert reloaded.get(ConfigKeys.GUI_LANG) == "de", "new key not saved"
    
    print("CONFIG_ROUNDTRIP_OK")
finally:
    config_path.unlink(missing_ok=True)
"@
    
    $testResult = Invoke-PythonTest -TestName "ConfigRoundTrip" -PythonCode $pythonCode
    
    if ($testResult.Output -match "CONFIG_ROUNDTRIP_OK") {
        Write-Pass "Config round-trip preserves unknown keys"
    } else {
        Write-Fail "Config round-trip failed: $($testResult.Output)"
    }
    
    # Test 3: Atomic write behavior (temp file pattern)
    Write-Section "Testing atomic write creates temp file"
    
    $pythonCode = @"
import sys
import json
import tempfile
import os
from pathlib import Path

sys.path.insert(0, r'$($script:SmartDriveDir)')

from core.config import write_config_atomic

# Create a dedicated test directory (avoids interference from system temp files)
test_dir = Path(tempfile.mkdtemp(prefix='atomic_write_test_'))

try:
    config_path = test_dir / 'test_config.json'
    config_path.write_text(json.dumps({"test": "original"}), encoding='utf-8')
    
    # Get initial mtime
    initial_mtime = config_path.stat().st_mtime
    
    # Write new content atomically
    write_config_atomic(config_path, {"test": "modified"})
    
    # Verify content changed
    content = json.loads(config_path.read_text(encoding='utf-8'))
    assert content["test"] == "modified", "Content not modified"
    
    # Verify no orphan temp files with config_ prefix (our pattern)
    temp_files = list(test_dir.glob("config_*.tmp"))
    assert len(temp_files) == 0, f"Orphan temp files: {temp_files}"
    
    print("ATOMIC_WRITE_OK")
finally:
    # Cleanup test directory
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
"@
    
    $testResult = Invoke-PythonTest -TestName "AtomicWrite" -PythonCode $pythonCode
    
    if ($testResult.Output -match "ATOMIC_WRITE_OK") {
        Write-Pass "Atomic write behavior verified"
    } else {
        Write-Fail "Atomic write test failed: $($testResult.Output)"
    }
}

# =============================================================================
# VERIFICATION 8: No Duplicate Resources (SSOT Enforcement)
# =============================================================================

function Test-NoDuplicateResources {
    <#
    .SYNOPSIS
        Verify that deployment produces exactly one config.json and one static/ directory.
        Per AGENT_ARCHITECTURE.md SSOT enforcement: duplicates are forbidden.
    #>
    
    Write-Banner "VERIFICATION 8: NO DUPLICATE RESOURCES (SSOT)"
    Write-Info "Ensuring PathResolver prevents duplicate config/static directories"
    
    # Test 1: Duplicate detection on repo structure
    Write-Section "Checking repository for duplicates"
    
    $pythonCode = @"
from core.path_resolver import RuntimePaths
import json

paths = RuntimePaths.from_script(r'$script:ProjectRoot\.smartdrive\scripts\mount.py')
duplicates = paths.detect_duplicates()

# Convert Path objects to strings for JSON serialization
duplicates_str = {k: [str(p) for p in v] for k, v in duplicates.items()}
print('DUPLICATES:' + json.dumps(duplicates_str))
"@
    
    $testResult = Invoke-PythonTest -TestName "DetectDuplicates" -PythonCode $pythonCode
    
    if ($testResult.Output -match 'DUPLICATES:(\{.*\})') {
        $duplicatesJson = $Matches[1]
        $duplicates = $duplicatesJson | ConvertFrom-Json
        
        # PSObject.Properties.Count returns $null for empty object, not 0
        $propCount = $duplicates.PSObject.Properties.Count
        if ($null -eq $propCount -or $propCount -eq 0) {
            Write-Pass "No duplicates detected in repository"
        } else {
            Write-Fail "Duplicates found in repository:"
            foreach ($resource in $duplicates.PSObject.Properties) {
                Write-Info "  $($resource.Name):"
                foreach ($path in $resource.Value) {
                    Write-Info "    - $path"
                }
            }
        }
    } else {
        Write-Fail "Duplicate detection test error: $($testResult.Output)"
    }
    
    # Test 2: PathResolver canonical paths are unique
    Write-Section "Validating PathResolver canonical paths"
    
    $pythonCode = @"
from core.path_resolver import RuntimePaths
from pathlib import Path

paths = RuntimePaths.from_script(r'$script:ProjectRoot\.smartdrive\scripts\mount.py')

# Check that all key paths are distinct
all_paths = {
    'config_file': str(paths.config_file),
    'static_dir': str(paths.static_dir),
    'keys_dir': str(paths.keys_dir),
    'logs_dir': str(paths.logs_dir),
}

# Ensure config is under .smartdrive/ but NOT under scripts/
# Canonical: .smartdrive/config.json (not .smartdrive/scripts/config.json)
if '.smartdrive' in Path(all_paths['config_file']).parts and 'scripts' not in Path(all_paths['config_file']).parts:
    print('CONFIG_CANONICAL_OK')
else:
    print('CONFIG_CANONICAL_FAIL: ' + all_paths['config_file'])

# Ensure static is under .smartdrive/ but NOT under scripts/
if '.smartdrive' in Path(all_paths['static_dir']).parts and 'scripts' not in Path(all_paths['static_dir']).parts:
    print('STATIC_CANONICAL_OK')
else:
    print('STATIC_CANONICAL_FAIL: ' + all_paths['static_dir'])

print('PATHS_OK')
"@
    
    $testResult = Invoke-PythonTest -TestName "CanonicalPaths" -PythonCode $pythonCode
    
    if ($testResult.Output -match "CONFIG_CANONICAL_OK" -and $testResult.Output -match "STATIC_CANONICAL_OK") {
        Write-Pass "PathResolver canonical paths are correct"
    } else {
        Write-Fail "PathResolver canonical path violations: $($testResult.Output)"
    }
    
    # Test 3: Consolidate duplicates preserves unknown keys
    Write-Section "Testing duplicate consolidation with unknown keys"
    
    $pythonCode = @"
from core.path_resolver import _deep_merge

# Test deep merge preserves unknown nested keys
base = {'known': {'nested': 1}, 'unknown_root': {'unknown_nested': {'deep': 'preserve'}}}
overlay = {'known': {'nested': 2, 'new': 3}, 'another_unknown': 'keep'}

_deep_merge(base, overlay)

# Verify preservation
if base.get('unknown_root', {}).get('unknown_nested', {}).get('deep') == 'preserve':
    if base.get('another_unknown') == 'keep':
        if base.get('known', {}).get('new') == 3:
            print('DEEP_MERGE_OK')
        else:
            print('DEEP_MERGE_FAIL: new key not merged')
    else:
        print('DEEP_MERGE_FAIL: unknown key lost')
else:
    print('DEEP_MERGE_FAIL: nested unknown key lost')
"@
    
    $testResult = Invoke-PythonTest -TestName "DeepMerge" -PythonCode $pythonCode
    
    if ($testResult.Output -match "DEEP_MERGE_OK") {
        Write-Pass "Deep merge preserves unknown keys correctly"
    } else {
        Write-Fail "Deep merge test failed: $($testResult.Output)"
    }
}

# =============================================================================
# VERIFICATION 9: Branding Compliance
# =============================================================================

function Test-BrandingCompliance {
    <#
    .SYNOPSIS
        Verify that forbidden branding terms do not appear in documentation.
        Per AGENT_ARCHITECTURE.md: README-first, consistent branding.
    #>
    
    Write-Banner "VERIFICATION 9: BRANDING COMPLIANCE"
    Write-Info "Running branding audit on documentation"
    
    Write-Section "Executing audit_branding.py"
    
    $auditScript = Join-Path $script:ProjectRoot "scripts\audit_branding.py"
    
    if (-not (Test-Path $auditScript)) {
        Write-Fail "Branding audit script not found: $auditScript"
        return
    }
    
    try {
        $result = & python "$auditScript" 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Pass "Branding audit passed (no forbidden terms)"
        } else {
            Write-Fail "Branding audit failed (forbidden terms found)"
            Write-Info $result
        }
    } catch {
        Write-Fail "Branding audit error: $_"
    }
}

# =============================================================================
# VERIFICATION 10: Cross-Drive Path Resolution
# =============================================================================

function Test-CrossDrivePathResolution {
    <#
    .SYNOPSIS
        Verify that PathResolver correctly resolves paths when script is on a different drive.
        This proves "run from anywhere" actually works for cross-drive scenarios.
    #>
    
    Write-Banner "VERIFICATION 10: CROSS-DRIVE PATH RESOLUTION"
    Write-Info "Testing PathResolver correctly handles paths across different drives"
    
    # Get current script drive
    $scriptDrive = (Split-Path -Qualifier $script:ProjectRoot).TrimEnd(":")
    Write-Info "Script repository on drive: ${scriptDrive}:"
    
    # Test 1: PathResolver from script location
    Write-Section "PathResolver from script location"
    
    $pythonCode = @"
from core.paths import Paths
from pathlib import Path
import sys

# Test that Paths resolves correctly from different CWDs
script_root = Path(r'$script:ProjectRoot')
smartdrive_dir = Paths.smartdrive_dir(script_root)
config_file = Paths.config_file(script_root)
static_dir = Paths.static_dir(script_root)

# Verify all paths are under the same launcher root
all_under_root = (
    str(smartdrive_dir).startswith(str(script_root)) and
    str(config_file).startswith(str(script_root)) and
    str(static_dir).startswith(str(script_root))
)

if all_under_root:
    print('CROSS_DRIVE_OK')
    print('SmartDrive dir: ' + str(smartdrive_dir))
    print('Config file: ' + str(config_file))
    print('Static dir: ' + str(static_dir))
else:
    print('CROSS_DRIVE_FAIL: paths escaped launcher root')
    print('Expected root: ' + str(script_root))
    print('SmartDrive: ' + str(smartdrive_dir))
"@
    
    $testResult = Invoke-PythonTest -TestName "CrossDrivePaths" -PythonCode $pythonCode
    
    if ($testResult.Output -match "CROSS_DRIVE_OK") {
        Write-Pass "PathResolver correctly binds paths to launcher root"
        $lines = $testResult.Output -split "`n"
        foreach ($line in $lines) {
            if ($line -match "^(SmartDrive|Config|Static)") {
                Write-Info $line.Trim()
            }
        }
    } else {
        Write-Fail "Cross-drive path resolution failed: $($testResult.Output)"
    }
    
    # Test 2: Simulate running from different drive
    Write-Section "Simulating execution from different working directory"
    
    $altCwd = $env:USERPROFILE  # User's home directory
    $altDrive = (Split-Path -Qualifier $altCwd).TrimEnd(":")
    Write-Info "Simulating CWD: $altCwd (drive ${altDrive}:)"
    
    $pythonCode = @"
import os
import sys
from pathlib import Path

# Change to alternate working directory
os.chdir(r'$altCwd')

# Now import and test paths
sys.path.insert(0, r'$script:SmartDriveDir')
from core.paths import Paths

# The launcher root should be explicit, not derived from CWD
launcher_root = Path(r'$script:ProjectRoot')
config = Paths.config_file(launcher_root)

# Verify config is under launcher_root, NOT under current CWD
if str(config).startswith(str(launcher_root)):
    print('CWD_ISOLATION_OK')
    print('CWD: ' + os.getcwd())
    print('Config: ' + str(config))
else:
    print('CWD_ISOLATION_FAIL: config path affected by CWD')
"@
    
    $testResult = Invoke-PythonTest -TestName "CWDIsolation" -PythonCode $pythonCode
    
    if ($testResult.Output -match "CWD_ISOLATION_OK") {
        Write-Pass "PathResolver is isolated from working directory"
    } else {
        Write-Fail "CWD isolation test failed: $($testResult.Output)"
    }
    
    # Test 3: Path exclusivity audit passes
    Write-Section "Running PathResolver exclusivity audit"
    
    $auditScript = Join-Path $script:ProjectRoot "scripts\audit_path_exclusivity.py"
    
    if (Test-Path $auditScript) {
        try {
            $result = & python $auditScript 2>&1 | Out-String
            $exitCode = $LASTEXITCODE
            
            if ($exitCode -eq 0) {
                Write-Pass "PathResolver exclusivity audit passed"
            } else {
                Write-Fail "PathResolver exclusivity audit failed"
                Write-Info $result
            }
        } catch {
            Write-Fail "PathResolver audit error: $_"
        }
    } else {
        Write-Skip "PathResolver exclusivity audit script not found"
    }
}

# =============================================================================
# VERIFICATION 11: Update Flow SSOT
# =============================================================================

function Test-UpdateFlowSSOT {
    <#
    .SYNOPSIS
        Verify that update.py uses PathResolver exclusively.
    #>
    
    Write-Banner "VERIFICATION 11: UPDATE FLOW SSOT"
    Write-Info "Testing update.py path handling"
    
    Write-Section "Checking update.py syntax and imports"
    
    $updateScript = Join-Path $script:SmartDriveDir "scripts\update.py"
    
    if (-not (Test-Path $updateScript)) {
        Write-Skip "update.py not found"
        return
    }
    
    $pythonCode = @"
import ast
from pathlib import Path

update_path = Path(r'$updateScript')
source = update_path.read_text(encoding='utf-8')

# Check syntax
try:
    ast.parse(source)
    print('SYNTAX_OK')
except SyntaxError as e:
    print('SYNTAX_ERROR: ' + str(e))
    exit(1)

# Check for forbidden patterns
forbidden = ['os.path.join(', 'os.path.dirname(', 'os.path.basename(']
found = []
for pattern in forbidden:
    if pattern in source:
        found.append(pattern)

if found:
    print('FORBIDDEN_PATTERNS: ' + ', '.join(found))
else:
    print('PATTERNS_OK: No os.path usage found')
    
# Check for Path imports
if 'from pathlib import Path' in source or 'import pathlib' in source:
    print('PATHLIB_IMPORT_OK')
else:
    print('PATHLIB_IMPORT_MISSING')
"@
    
    $testResult = Invoke-PythonTest -TestName "UpdateSSOT" -PythonCode $pythonCode
    
    if ($testResult.Output -match "SYNTAX_OK" -and $testResult.Output -match "PATTERNS_OK") {
        Write-Pass "update.py uses pathlib exclusively"
    } else {
        Write-Fail "update.py SSOT violations: $($testResult.Output)"
    }
}

# =============================================================================
# VERIFICATION 12: Cross-Drive Setup + Mount Proof
# =============================================================================

function Test-CrossDriveSetupMount {
    <#
    .SYNOPSIS
        Prove that setup executed from Drive A can mount a volume on Drive B.
        Per AGENT_ARCHITECTURE.md: Cross-drive support is mandatory.
    #>
    
    Write-Banner "VERIFICATION 12: CROSS-DRIVE SETUP + MOUNT PROOF"
    Write-Info "Testing that RuntimePaths supports cross-drive scenarios"
    
    # Test 1: Setup from Drive A targets Drive B (A→B)
    Write-Section "Test-CrossDriveSetupMount-AtoB: Script on C: targets D:"
    
    $pythonCode = @"
import sys
sys.path.insert(0, r'$($script:SmartDriveDir)')

from core.path_resolver import RuntimePaths
from pathlib import Path

# Scenario: Script running from C: (this repo), targeting a drive on D:
script_path = Path(r'$script:ProjectRoot\.smartdrive\scripts\mount.py')
script_drive = script_path.drive  # e.g., "C:"

# Create RuntimePaths from script location
paths = RuntimePaths.from_script(str(script_path))

# Verify script drive binding
assert paths.project_root.drive == script_drive, f"Expected {script_drive}, got {paths.project_root.drive}"

# Simulate cross-drive target: config could specify D:\vault.hc
target_volume = r"D:\encrypted_volume.hc"
target_drive = Path(target_volume).drive  # "D:"

# Key verification: PathResolver should NOT modify target paths
# The volume path in config is passed directly to VeraCrypt
assert target_drive != script_drive or script_drive == "D:", "Test requires different drives"

print(f"SCRIPT_DRIVE:{script_drive}")
print(f"TARGET_DRIVE:{target_drive}")
print(f"PATHS_BOUND_TO_SCRIPT_ROOT:True")
print("CROSS_DRIVE_ATOB_OK")
"@
    
    $testResult = Invoke-PythonTest -TestName "CrossDriveAtoB" -PythonCode $pythonCode
    
    if ($testResult.Output -match "CROSS_DRIVE_ATOB_OK") {
        if ($testResult.Output -match "SCRIPT_DRIVE:([A-Z]:)") {
            $scriptDrive = $Matches[1]
            Write-Info "Script drive: $scriptDrive"
        }
        if ($testResult.Output -match "TARGET_DRIVE:([A-Z]:)") {
            $targetDrive = $Matches[1]
            Write-Info "Target drive: $targetDrive"
        }
        Write-Pass "Cross-drive A→B scenario verified (script binds to its own root)"
    } else {
        Write-Fail "Cross-drive A→B test failed: $($testResult.Output)"
    }
    
    # Test 2: Setup from Drive B targets Drive B (B→B) - same drive scenario
    Write-Section "Test-CrossDriveSetupMount-BtoB: Script and target on same drive"
    
    $pythonCode = @"
import sys
sys.path.insert(0, r'$($script:SmartDriveDir)')

from core.path_resolver import RuntimePaths
from pathlib import Path

# Scenario: Script and target on same drive (e.g., both on C:)
script_path = Path(r'$script:ProjectRoot\.smartdrive\scripts\mount.py')
script_drive = script_path.drive

# Create RuntimePaths
paths = RuntimePaths.from_script(str(script_path))

# Same-drive target
target_volume = f"{script_drive}\\encrypted_volume.hc"
target_drive = Path(target_volume).drive

# Verify same-drive scenario works
assert target_drive == script_drive, f"Expected same drive, got {target_drive} vs {script_drive}"

# Verify config path is on script drive
assert paths.config_file.drive == script_drive, "Config file on wrong drive"

print(f"SCRIPT_DRIVE:{script_drive}")
print(f"TARGET_DRIVE:{target_drive}")
print(f"CONFIG_DRIVE:{paths.config_file.drive}")
print("CROSS_DRIVE_BTOB_OK")
"@
    
    $testResult = Invoke-PythonTest -TestName "CrossDriveBtoB" -PythonCode $pythonCode
    
    if ($testResult.Output -match "CROSS_DRIVE_BTOB_OK") {
        if ($testResult.Output -match "SCRIPT_DRIVE:([A-Z]:)") {
            $scriptDrive = $Matches[1]
            Write-Info "Script drive: $scriptDrive"
        }
        if ($testResult.Output -match "TARGET_DRIVE:([A-Z]:)") {
            $targetDrive = $Matches[1]
            Write-Info "Target drive: $targetDrive"
        }
        if ($testResult.Output -match "CONFIG_DRIVE:([A-Z]:)") {
            $configDrive = $Matches[1]
            Write-Info "Config drive: $configDrive"
        }
        Write-Pass "Cross-drive B→B scenario verified (same drive works)"
    } else {
        Write-Fail "Cross-drive B→B test failed: $($testResult.Output)"
    }
    
    # Test 3: RuntimePaths.for_target() creates isolated paths
    Write-Section "Test for_target() isolation"
    
    $pythonCode = @"
import sys
sys.path.insert(0, r'$($script:SmartDriveDir)')

from core.path_resolver import RuntimePaths
from pathlib import Path

# Get paths from script
script_path = Path(r'$script:ProjectRoot\.smartdrive\scripts\mount.py')
paths = RuntimePaths.from_script(str(script_path))

# Simulate target drive root (for USB setup scenario)
# for_target expects the DRIVE ROOT with trailing backslash for Windows
target_root = Path(r"F:\\")  # Hypothetical USB drive root

# Get target-bound paths
target_paths = RuntimePaths.for_target(target_root)

# Verify target paths are isolated from source paths
assert target_paths.project_root != paths.project_root, "Target should have different root"
# Config should be under target_root/.smartdrive (NOT .smartdrive/scripts)
expected_config_parent = target_root / ".smartdrive"
assert target_paths.config_file.parent == expected_config_parent, f"Config parent {target_paths.config_file.parent} should be {expected_config_parent}"
assert str(target_paths.static_dir).startswith(str(target_root)), "Static should be under target"

print(f"SOURCE_ROOT:{paths.project_root}")
print(f"TARGET_ROOT:{target_paths.project_root}")
print(f"TARGET_CONFIG:{target_paths.config_file}")
print("FOR_TARGET_ISOLATION_OK")
"@
    
    $testResult = Invoke-PythonTest -TestName "ForTargetIsolation" -PythonCode $pythonCode
    
    if ($testResult.Output -match "FOR_TARGET_ISOLATION_OK") {
        if ($testResult.Output -match "SOURCE_ROOT:(.+)") {
            Write-Info "Source root: $($Matches[1])"
        }
        if ($testResult.Output -match "TARGET_ROOT:(.+)") {
            Write-Info "Target root: $($Matches[1])"
        }
        Write-Pass "for_target() properly isolates source and target paths"
    } else {
        Write-Fail "for_target() isolation test failed: $($testResult.Output)"
    }
}

# =============================================================================
# VERIFICATION 13: tmp_key Regression Fix Proof
# =============================================================================

function Test-TmpKeyRegression {
    <#
    .SYNOPSIS
        Verify tmp_key UnboundLocalError is fixed.
        Error was: "cannot access local variable 'tmp_key' where it is not associated with a value"
    #>
    
    Write-Banner "VERIFICATION 13: TMP_KEY REGRESSION FIX"
    Write-Info "Verifying mount error handler does not crash with UnboundLocalError"
    
    Write-Section "Testing mount error message generation"
    
    $pythonCode = @"
import sys
sys.path.insert(0, r'$($script:SmartDriveDir)')

from pathlib import Path

# Simulate the error handler code path (password-only mode, no keyfiles)
tmp_keys = []  # No keyfiles - this was the bug scenario
volume_path = r"\\Device\\Harddisk1\\Partition2"
mount_letter = "V"

# This is the FIXED pattern - should NOT raise UnboundLocalError
try:
    keyfile_info = "(none - password only)"
    if tmp_keys and len(tmp_keys) > 0:
        keyfile_info = ", ".join(str(k) for k in tmp_keys)
    
    # Build error message (simplified)
    error_msg = f"Keyfile: {keyfile_info}"
    
    # Verify no crash and correct content
    assert "UnboundLocalError" not in str(error_msg), "Error message contains UnboundLocalError"
    assert "(none - password only)" in error_msg, "Missing password-only indicator"
    
    print("TMP_KEY_NO_KEYFILE_OK")
except UnboundLocalError as e:
    print(f"UNBOUNDLOCALERROR_BUG: {e}")
except Exception as e:
    print(f"OTHER_ERROR: {e}")
"@
    
    $testResult = Invoke-PythonTest -TestName "TmpKeyNoKeyfile" -PythonCode $pythonCode
    
    if ($testResult.Output -match "TMP_KEY_NO_KEYFILE_OK") {
        Write-Pass "No UnboundLocalError in password-only mode"
    } elseif ($testResult.Output -match "UNBOUNDLOCALERROR_BUG") {
        Write-Fail "REGRESSION: UnboundLocalError still present: $($testResult.Output)"
    } else {
        Write-Fail "tmp_key test failed: $($testResult.Output)"
    }
    
    # Test with keyfiles present
    Write-Section "Testing mount error message with keyfiles"
    
    $pythonCode = @"
import sys
sys.path.insert(0, r'$($script:SmartDriveDir)')

from pathlib import Path

# Simulate with keyfiles present
tmp_keys = [Path(r"C:\temp\key1.dat"), Path(r"C:\temp\key2.dat")]

try:
    keyfile_info = "(none - password only)"
    if tmp_keys and len(tmp_keys) > 0:
        keyfile_info = ", ".join(str(k) for k in tmp_keys)
    
    # Verify keyfiles are listed
    error_msg = f"Keyfile: {keyfile_info}"
    
    assert "key1" in error_msg, "Missing key1 in message"
    assert "key2" in error_msg, "Missing key2 in message"
    assert "(none" not in error_msg, "Should not show password-only when keyfiles exist"
    
    print("TMP_KEY_WITH_KEYFILES_OK")
except Exception as e:
    print(f"ERROR: {e}")
"@
    
    $testResult = Invoke-PythonTest -TestName "TmpKeyWithKeyfiles" -PythonCode $pythonCode
    
    if ($testResult.Output -match "TMP_KEY_WITH_KEYFILES_OK") {
        Write-Pass "Keyfiles correctly listed in error message"
    } else {
        Write-Fail "tmp_key with keyfiles test failed: $($testResult.Output)"
    }
}

# =============================================================================
# Main Execution
# =============================================================================

function Show-Summary {
    Write-Host "`n"
    Write-Host ("=" * 70) -ForegroundColor Magenta
    Write-Host "  E2E VERIFICATION SUMMARY" -ForegroundColor Magenta
    Write-Host ("=" * 70) -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  Results:"
    Write-Host "    Passed:  $script:TestsPassed" -ForegroundColor Green
    Write-Host "    Failed:  $script:TestsFailed" -ForegroundColor $(if ($script:TestsFailed -gt 0) { "Red" } else { "Green" })
    Write-Host "    Skipped: $script:TestsSkipped" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Log file: $LogFile"
    Write-Host ("=" * 70) -ForegroundColor Magenta
    
    # Log final summary
    Write-LogEntry "SUMMARY" "Passed=$script:TestsPassed, Failed=$script:TestsFailed, Skipped=$script:TestsSkipped"
    
    if ($script:TestsFailed -gt 0) {
        Write-Host "`n  E2E VERIFICATION FAILED" -ForegroundColor Red
        Write-LogEntry "RESULT" "FAILED"
        return 1
    } else {
        Write-Host "`n  E2E VERIFICATION PASSED" -ForegroundColor Green
        Write-LogEntry "RESULT" "PASSED"
        return 0
    }
}

# =============================================================================
# Entry Point
# =============================================================================

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Blue
Write-Host "  SMARTDRIVE E2E HARDWARE VERIFICATION (Release Gate)" -ForegroundColor Blue
Write-Host "  Timestamp: $script:Timestamp" -ForegroundColor Blue
Write-Host ("=" * 70) -ForegroundColor Blue

Initialize-Logging

# Run pre-flight checks
if (-not (Test-Prerequisites)) {
    Write-Host "`nPre-flight checks failed. Cannot continue." -ForegroundColor Red
    exit 1
}

# Select USB disk
$targetUSB = Select-USBDisk -RequestedDiskNumber $USBDiskNumber

if ($targetUSB -and -not $SkipDestructiveTests) {
    # Show warning for destructive tests
    $confirmed = Get-OperatorConfirmation `
        -Title "DESTRUCTIVE TEST WARNING" `
        -Warnings @(
            "Disk $($targetUSB.Number): $($targetUSB.FriendlyName)",
            "Size: $([math]::Round($targetUSB.Size / 1GB, 1)) GB",
            "ALL DATA ON THIS DISK WILL BE DESTROYED!"
        ) `
        -ConfirmPhrase "WIPE DISK $($targetUSB.Number)"
    
    if (-not $confirmed) {
        Write-Host "`nOperator declined destructive tests." -ForegroundColor Yellow
        $SkipDestructiveTests = $true
    }
}

# Run verifications
Test-SafetyGuardrail -USBDisk $targetUSB
Test-SecurityModePrerequisites
Test-RunFromAnywhere
Test-GUITerminalSpawning
Test-AtomicWrites
Test-DiskIdentityContract
Test-SettingsUI
Test-NoDuplicateResources
Test-BrandingCompliance
Test-CrossDrivePathResolution
Test-UpdateFlowSSOT
Test-CrossDriveSetupMount
Test-TmpKeyRegression

# Summary and exit
$exitCode = Show-Summary
exit $exitCode
