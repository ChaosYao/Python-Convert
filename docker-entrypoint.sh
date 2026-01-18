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
fi

# Switch to appuser and execute the original command
exec gosu appuser "$@"
