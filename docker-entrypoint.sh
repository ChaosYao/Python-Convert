#!/bin/bash
set -e

# Fix permissions for /root/.ndn if mounted
# This script runs as root (before USER directive takes effect)
if [ -d "/root/.ndn" ]; then
    # Make directory writable by appuser (uid 1000)
    # This allows SQLite to create temporary files
    chown -R 1000:1000 /root/.ndn 2>/dev/null || {
        # If chown fails (e.g., on read-only mount), try chmod
        chmod -R 777 /root/.ndn 2>/dev/null || true
    }
    echo "Fixed permissions for /root/.ndn"
    
    # Check if PIB database exists and is valid
    PIB_DB="/root/.ndn/pib.db"
    if [ -f "$PIB_DB" ]; then
        # Check if database has tpmInfo table using sqlite3
        # If sqlite3 is not available, we'll skip the check
        if command -v sqlite3 >/dev/null 2>&1; then
            if ! sqlite3 "$PIB_DB" "SELECT name FROM sqlite_master WHERE type='table' AND name='tpmInfo';" 2>/dev/null | grep -q "tpmInfo"; then
                echo "WARNING: PIB database exists but missing tpmInfo table. Removing corrupted database..."
                rm -f "$PIB_DB"
                # Also remove SQLite temporary files if they exist
                rm -f "${PIB_DB}-shm" "${PIB_DB}-wal" 2>/dev/null || true
                echo "Removed corrupted database. KeychainSqlite3 will create a new one."
            fi
        else
            # If sqlite3 is not available, check file size - empty or very small files are likely corrupted
            if [ ! -s "$PIB_DB" ] || [ $(stat -f%z "$PIB_DB" 2>/dev/null || stat -c%s "$PIB_DB" 2>/dev/null || echo 0) -lt 100 ]; then
                echo "WARNING: PIB database file is empty or too small. Removing..."
                rm -f "$PIB_DB"
                rm -f "${PIB_DB}-shm" "${PIB_DB}-wal" 2>/dev/null || true
                echo "Removed corrupted database. KeychainSqlite3 will create a new one."
            fi
        fi
    fi
fi

# Switch to appuser and execute the original command
exec gosu appuser "$@"
