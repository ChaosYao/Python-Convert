#!/bin/bash
# Simple entrypoint that runs as root
# Since the mounted /root/.ndn directory requires root access,
# we run the application as root user

# Execute the command - error handling is done in Python code
# Python code will catch errors and keep the container running
exec "$@"
