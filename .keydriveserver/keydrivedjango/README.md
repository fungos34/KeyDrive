# KeyDrive Django Server

CHG-20251221-013: Django refactor of KeyDrive server.

## Overview

This is the Django version of the KeyDrive server, providing:
- **Admin UI**: Full-featured admin interface at `/admin/`
- **REST API**: DRF-powered API at `/api/`
- **Better ORM**: Django ORM with migrations support

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Apply migrations
python manage.py migrate

# Create admin superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver

# Access:
# - Admin: http://127.0.0.1:8000/admin/
# - API: http://127.0.0.1:8000/api/
```

## API Endpoints

### Verification
- `POST /api/verify` - Verify integrity hash
- `POST /api/check` - Legacy compatibility endpoint

### Updates
- `GET /api/update/` - List all updates
- `POST /api/update/check/` - Check for updates
- `GET /api/update/download/latest` - Download latest
- `GET /api/update/download/{version}` - Download specific version

### Seeds
- `POST /api/seeds/store/` - Store encrypted seed
- `POST /api/seeds/retrieve/` - Retrieve encrypted seed
- `POST /api/seeds/lock/` - Lock seed

### Keys
- `GET /api/keys/` - List all keys
- `POST /api/keys/report-lost/` - Report key as lost
- `POST /api/keys/revoke/` - Revoke a key
- `GET /api/keys/{fingerprint}/check/` - Check key status

### Devices
- `GET /api/devices/` - List all devices
- `POST /api/devices/{hash}/lock/` - Lock device
- `POST /api/devices/{hash}/unlock/` - Unlock device

## Admin Features

The Django admin provides:
- **Device Management**: View, lock/unlock devices
- **Seed Management**: View encrypted seeds, lock/unlock
- **Key Status**: Track hardware key status (active/lost/revoked)
- **Update Management**: Upload and manage update packages
- **Verification Logs**: Audit trail of all verification attempts

## Environment Variables

```bash
DJANGO_SECRET_KEY=your-production-secret-key
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your-domain.com,api.your-domain.com
CORS_ALLOWED_ORIGINS=https://your-domain.com
TRUSTED_SIGNERS=fingerprint1,fingerprint2
```

## Production Deployment

```bash
# Collect static files
python manage.py collectstatic

# Run with gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 config.wsgi:application
```

## Migration from Flask

The Django server is API-compatible with the Flask version. Both can run 
simultaneously on different ports during migration. Database schema is 
similar but managed through Django migrations.
