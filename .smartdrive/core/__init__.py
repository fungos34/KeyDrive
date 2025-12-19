# SmartDrive SSOT core modules
# This package contains all single-source-of-truth modules for the SmartDrive runtime.
# =============================================================================
# Version
# =============================================================================
from .version import VERSION

# =============================================================================
# Resource Resolution (SSOT for icons and assets)
# =============================================================================
from .resources import (
    # Base resolution
    get_base_dir,
    resolve_icon_path,
    get_icon_candidates,
    
    # Platform-aware icon getters
    get_app_icon_path,
    get_mounted_icon_path,
    get_unmounted_icon_path,
    
    # Theme-aware icon getters (SSOT)
    get_logo_main_ico,
    get_logo_main_png,
    get_logo_for_platform,
    
    # Validation
    validate_qicon,
    
    # Diagnostics
    log_resource_diagnostics,
)

# =============================================================================
# Public API
# =============================================================================
__all__ = [
    # Version
    "VERSION",
    
    # Resource resolution
    "get_base_dir",
    "resolve_icon_path",
    "get_icon_candidates",
    "get_app_icon_path",
    "get_mounted_icon_path",
    "get_unmounted_icon_path",
    
    # Theme-aware (SSOT)
    "get_logo_main_ico",
    "get_logo_main_png",
    "get_logo_for_platform",
    
    # Validation
    "validate_qicon",
    
    # Diagnostics
    "log_resource_diagnostics",
]