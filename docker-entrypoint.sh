#!/bin/bash
set -e

# Simple entrypoint that runs as root
# Since the mounted /root/.ndn directory requires root access,
# we run the application as root user

# Just execute the command directly (no user switching needed)
exec "$@"
