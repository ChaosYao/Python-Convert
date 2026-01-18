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
    
    # Check if PIB database exists and is accessible
    PIB_DB="/root/.ndn/pib.db"
    if [ -f "$PIB_DB" ]; then
        echo "PIB database file exists: $PIB_DB"
        
        # Check file permissions
        ls -la "$PIB_DB" || true
        
        # Check if database is readable and has tpmInfo table
        if command -v sqlite3 >/dev/null 2>&1; then
            # First, check if we can open the database at all
            if sqlite3 "$PIB_DB" "PRAGMA integrity_check;" >/dev/null 2>&1; then
                echo "Database integrity check passed"
                
                # Check for tpmInfo table (case-insensitive check)
                # KeychainSqlite3 may use TpmInfo (capital T) or tpmInfo (lowercase t)
                TABLE_CHECK=$(sqlite3 "$PIB_DB" "SELECT name FROM sqlite_master WHERE type='table' AND (name='tpmInfo' OR name='TpmInfo' OR name='TPMINFO');" 2>/dev/null | head -1 || echo "")
                
                if [ -n "$TABLE_CHECK" ]; then
                    echo "Found tpmInfo table (as: $TABLE_CHECK)"
                    
                    # Check if database is in WAL mode and checkpoint if needed
                    WAL_MODE=$(sqlite3 "$PIB_DB" "PRAGMA journal_mode;" 2>/dev/null | head -1 || echo "unknown")
                    echo "Database journal mode: $WAL_MODE"
                    
                    if [ "$WAL_MODE" = "wal" ]; then
                        echo "Database is in WAL mode, performing checkpoint..."
                        sqlite3 "$PIB_DB" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
                    fi
                else
                    echo "WARNING: tpmInfo/TpmInfo table not found in database"
                    echo "Database tables:"
                    sqlite3 "$PIB_DB" ".tables" 2>/dev/null || true
                    
                    # Try to create the table if it doesn't exist
                    # KeychainSqlite3 expects TpmInfo (capital T) based on C++ implementation
                    echo "Attempting to create TpmInfo table..."
                    sqlite3 "$PIB_DB" "CREATE TABLE IF NOT EXISTS TpmInfo(tpm_locator BLOB NOT NULL, PRIMARY KEY (tpm_locator));" 2>/dev/null && {
                        echo "Successfully created TpmInfo table"
                    } || {
                        echo "Failed to create TpmInfo table, but continuing..."
                    }
                fi
            else
                echo "WARNING: Cannot open database file, may be corrupted or locked"
                # Don't delete it, let the application handle the error
            fi
        else
            echo "sqlite3 command not available, skipping database validation"
        fi
        
        # Ensure SQLite temporary files directory is writable
        # SQLite needs to create -shm and -wal files in the same directory
        DB_DIR=$(dirname "$PIB_DB")
        if [ -w "$DB_DIR" ]; then
            echo "Database directory is writable: $DB_DIR"
        else
            echo "WARNING: Database directory is not writable: $DB_DIR"
            chmod 777 "$DB_DIR" 2>/dev/null || true
        fi
    else
        echo "PIB database file does not exist: $PIB_DB"
        echo "KeychainSqlite3 will create a new database on first run"
    fi
fi

# Switch to appuser and execute the original command
exec gosu appuser "$@"
