#!/bin/bash
# Social Monitor — Docker entrypoint
# Initializes data directory on first run, then starts the server.

set -e

DATA_DIR="${SM_DATA_DIR:-/app/data}"
echo "Social Monitor — data dir: $DATA_DIR"

# Ensure data directory structure
mkdir -p "$DATA_DIR/cookies" "$DATA_DIR/logs" "$DATA_DIR/social-auto-upload/cookies"
# Ensure tmp dir exists in app directory (for QR images etc.)
mkdir -p /app/tmp

# Initialize DB from image if not already present
if [ ! -f "$DATA_DIR/monitor.db" ]; then
    echo "First run: initializing database..."
    # Source DB from image (fresh) — server.py's migrate_db() handles table creation
    touch "$DATA_DIR/monitor.db"
fi

echo "Starting Social Monitor on port ${SM_PORT:-5408}..."
# Clear stale bytecode cache so Python always recompiles from source
rm -f /app/__pycache__/server*.pyc
exec python3 server.py
