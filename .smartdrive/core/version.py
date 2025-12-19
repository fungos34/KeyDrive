# core/version.py - SINGLE SOURCE OF TRUTH for version string
"""
This is the ONLY place where VERSION is defined.
All other modules MUST import VERSION from here.
"""

VERSION = "0.0.1"

# Build metadata (optional)
BUILD_ID = None  # Set by CI/CD if needed
COMPATIBILITY_VERSION = "2.0"  # Minimum compatible config schema version
