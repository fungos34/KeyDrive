# KeyDrive Server

**Development-Only Component** - Not deployed to KeyDrive devices.

## Purpose

KeyDrive Server is a backend service that provides:

1. **Integrity Verification** - Validate drive hashes against signed manifests
2. **Update Distribution** - Serve software updates to KeyDrive devices
3. **Encrypted Seed Storage** - Store/retrieve GPG-encrypted seeds by device ID
4. **Hardware Key Lockout** - Mark keys as lost and block associated devices

## Security Model

- Seeds are stored GPG-encrypted; server cannot decrypt them
- Key lockout requires admin authentication token
- All device IDs are hashed for privacy protection
- HTTPS required in production
- Rate limiting on all endpoints

## Architecture

```
.keydriveserver/
├── README.md           # This file
├── requirements.txt    # Python dependencies
├── config.py           # Server configuration
├── server.py           # Main Flask application
├── models.py           # SQLAlchemy database models
├── routes/
│   ├── __init__.py     # Route blueprints
│   ├── verify.py       # Integrity verification endpoints
│   ├── update.py       # Update distribution endpoints
│   ├── seeds.py        # Seed management endpoints
│   └── keys.py         # Key lockout management
├── database/
│   └── schema.sql      # Database schema reference
└── tests/
    └── test_server.py  # Server tests
```

## API Endpoints

### Health Check
- `GET /api/health` - Server health status

### Integrity Verification
- `POST /api/verify` - Validate device integrity hash
  - Body: `{"device_id": "...", "hash": "...", "version": "..."}`
  - Returns: `{"valid": true/false, "message": "..."}`

### Updates
- `GET /api/update/latest` - Get latest version info
- `GET /api/update/download/<version>` - Download update package

### Seed Storage
- `POST /api/seeds` - Store encrypted seed
  - Body: `{"device_id": "...", "encrypted_seed": "...", "key_fingerprints": [...], "salt": "..."}`
- `GET /api/seeds/<device_id>` - Retrieve encrypted seed
- `DELETE /api/seeds/<device_id>` - Remove seed (admin only)

### Key Lockout
- `POST /api/keys/report-lost` - Report key as lost (admin only)
  - Body: `{"fingerprint": "...", "reason": "...", "admin_token": "..."}`
- `GET /api/keys/<fingerprint>/status` - Check key status
- `POST /api/keys/unlock` - Unlock key (admin only)

## Configuration

Environment variables:
- `KEYDRIVE_SECRET_KEY` - Flask secret key
- `KEYDRIVE_ADMIN_TOKEN` - Admin authentication token
- `KEYDRIVE_DATABASE_URL` - SQLite database path (default: `keydrive.db`)
- `KEYDRIVE_DEBUG` - Enable debug mode (default: false)

## Running the Server

```bash
# Development
cd .keydriveserver
pip install -r requirements.txt
python server.py

# Production (use gunicorn)
gunicorn -w 4 -b 0.0.0.0:8000 server:app
```

## Database Schema

See `database/schema.sql` for the complete schema.

Main tables:
- `devices` - Device registration and verification tracking
- `seeds` - GPG-encrypted seed storage
- `keys` - Hardware key status (active/lost)
- `verification_log` - Audit log of verification attempts
- `updates` - Software update metadata

## Important Note

This server is **NOT deployed to KeyDrive devices**. It is excluded from the KeyDrive deployment process and should be hosted on a separate server infrastructure.
