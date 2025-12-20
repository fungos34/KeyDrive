# SmartDrive SSOT core modules
# This package contains all single-source-of-truth modules for the SmartDrive runtime.
# =============================================================================
# Version
# =============================================================================
# =============================================================================
# Resource Resolution (SSOT for icons and assets)
# =============================================================================
from .resources import (  # Base resolution; Platform-aware icon getters; Theme-aware icon getters (SSOT); Validation; Diagnostics
    get_app_icon_path,
    get_base_dir,
    get_icon_candidates,
    get_logo_for_platform,
    get_logo_main_ico,
    get_logo_main_png,
    get_mounted_icon_path,
    get_unmounted_icon_path,
    log_resource_diagnostics,
    resolve_icon_path,
    validate_qicon,
)
from .version import VERSION

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
