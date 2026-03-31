#!/bin/bash
# Entrypoint for sidecar container (runs as root / uid=0).
# Loop prevention is handled at the protocol level: sidecar-to-sidecar
# forwarding uses PEER_SIDECAR_PORT (default 19090), not the JRaft port (8181),
# so OUTPUT iptables rules never re-intercept the sidecar's own outbound traffic.

# Execute the command - error handling is done in Python code
# Python code will catch errors and keep the container running
exec "$@"
