"""
WSGI config for KeyDrive Server.

CHG-20251221-013: Django WSGI application.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
