#!/bin/bash
# Entrypoint for sidecar container (runs as root / uid=0, same as JRaft).
# Loop prevention via port separation: sidecar forwards to peer:19090 (not :8181),
# so iptables OUTPUT REDIRECT (--dport 8181) never catches sidecar outbound traffic.
# iptables init container must NOT include --uid-owner RETURN rule.

# Execute the command - error handling is done in Python code
# Python code will catch errors and keep the container running
exec "$@"
