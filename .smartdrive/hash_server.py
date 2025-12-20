#!/usr/bin/env python3
"""
Simple Hash Verification Server
===============================

A minimal Flask server that verifies script hashes against a database.
Run this on a trusted server to provide remote integrity verification.

Security Notes:
- Use HTTPS in production
- Implement proper authentication
- Rate limiting
- Audit logging
"""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

# Database file for known hashes
DB_FILE = Path(__file__).parent / "hash_database.json"


def load_database():
    """Load hash database."""
    if DB_FILE.exists():
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}


def save_database(db):
    """Save hash database."""
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)


@app.route("/api/generate-challenge", methods=["POST"])
def generate_challenge():
    """Generate a unique salt/challenge for verification."""
    salt = secrets.token_hex(32)  # 64 character hex string
    challenge_id = secrets.token_hex(16)  # Unique ID for this challenge

    # Store challenge temporarily (in production, use a database with expiration)
    challenges = load_challenges()
    challenges[challenge_id] = {"salt": salt, "timestamp": time.time(), "used": False}
    save_challenges(challenges)

    return jsonify(
        {
            "challenge_id": challenge_id,
            "salt": salt,
            "instructions": "Copy this salt to your SmartDrive and generate the challenge hash, then submit the result.",
        }
    )


@app.route("/api/verify-challenge", methods=["POST"])
def verify_challenge():
    """Verify a challenge response by hashing directory with salt."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        challenge_id = data.get("challenge_id")
        client_hash = data.get("client_hash")
        server_endpoint = data.get("server_endpoint", "").strip()

        if not all([challenge_id, client_hash, server_endpoint]):
            return jsonify({"error": "Missing challenge_id, client_hash, or server_endpoint"}), 400

        challenges = load_challenges()
        if challenge_id not in challenges:
            return jsonify({"error": "Invalid or expired challenge"}), 404

        challenge = challenges[challenge_id]
        if challenge["used"]:
            return jsonify({"error": "Challenge already used"}), 400

        # Check if challenge is expired (24 hours)
        if time.time() - challenge["timestamp"] > 24 * 3600:
            return jsonify({"error": "Challenge expired"}), 400

        # Mark challenge as used
        challenge["used"] = True
        save_challenges(challenges)

        # Server-side verification: hash our reference directory with the salt
        try:
            server_hash = hash_directory_with_salt_server(challenge["salt"])

            if client_hash == server_hash:
                return jsonify(
                    {"valid": True, "message": "Directory hash verification successful", "server_hash": server_hash}
                )
            else:
                return (
                    jsonify(
                        {
                            "valid": False,
                            "error": "Hash mismatch - directory may be tampered with",
                            "server_hash": server_hash,
                            "client_hash": client_hash,
                        }
                    ),
                    400,
                )

        except Exception as e:
            return jsonify({"valid": False, "error": f"Server hashing error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def load_challenges():
    """Load challenges database."""
    challenges_file = Path(__file__).parent / "challenges.json"
    if challenges_file.exists():
        with open(challenges_file, "r") as f:
            return json.load(f)
    return {}


def save_challenges(challenges):
    """Save challenges database."""
    challenges_file = Path(__file__).parent / "challenges.json"
    with open(challenges_file, "w") as f:
        json.dump(challenges, f, indent=2)


@app.route("/api/add-hash", methods=["POST"])
def add_hash():
    """Add a hash to the database (admin only - add authentication!)."""
    try:
        data = request.get_json()
        version = data.get("version")
        hash_value = data.get("hash")

        if not version or not hash_value:
            return jsonify({"error": "Missing version or hash"}), 400

        db = load_database()
        db[version] = hash_value
        save_database(db)

        return jsonify({"success": True, "version": version, "hash": hash_value[:16] + "..."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/list-versions", methods=["GET"])
def list_versions():
    """List all versions in database."""
    db = load_database()
    return jsonify({"versions": list(db.keys()), "count": len(db)})


def hash_directory_with_salt_server(salt: str) -> str:
    """Hash the server's reference scripts directory with salt file."""
    # Server maintains a clean reference copy of scripts
    reference_dir = Path(__file__).parent / "reference_scripts"

    if not reference_dir.exists():
        raise Exception(f"Reference scripts directory not found: {reference_dir}")

    # Create salt file in reference directory
    salt_file = reference_dir / ".challenge_salt"
    try:
        with open(salt_file, "w") as f:
            f.write(salt)

        # Hash the directory including the salt file
        result = hash_directory(reference_dir)
        return result

    finally:
        # Clean up salt file
        try:
            if salt_file.exists():
                salt_file.unlink()
        except:
            pass


def hash_directory(dir_path: Path) -> str:
    """Hash an entire directory recursively, including all files."""
    hash_obj = hashlib.sha256()

    # Get all files in sorted order for consistent hashing
    all_files = []
    for root, dirs, files in os.walk(dir_path):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in ["__pycache__", ".git"]]
        for file in files:
            # Include all files, including hidden ones like .challenge_salt
            all_files.append(str(Path(root) / file))

    all_files.sort()

    for file_path in all_files:
        # Include relative path in hash to detect file moves
        rel_path = os.path.relpath(file_path, dir_path)
        hash_obj.update(rel_path.encode("utf-8"))
        hash_obj.update(b"\x00")  # Separator

        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    hash_obj.update(chunk)
        except (OSError, IOError) as e:
            # Skip files that can't be read
            hash_obj.update(f"[ERROR: {e}]".encode("utf-8"))

        hash_obj.update(b"\x00")  # File separator

    return hash_obj.hexdigest()


if __name__ == "__main__":
    print("Hash Verification Server (Challenge-Response)")
    print("============================================")
    print(f"Database: {DB_FILE}")
    print("Challenges: challenges.json")
    print("Endpoints:")
    print("  POST /api/generate-challenge  - Generate unique salt")
    print("  POST /api/verify-challenge    - Verify challenge response")
    print("  POST /api/add-hash           - Add hash to database (admin)")
    print("  GET  /api/list-versions      - List known versions")
    print()
    print("Starting server on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
