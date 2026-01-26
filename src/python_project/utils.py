"""
Utility functions for the NDN/gRPC conversion project.
"""

import sys
import os
import socket
import logging


def setup_logging(level: str = "INFO") -> None:
    """
    Setup basic logging configuration.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def get_hostname() -> str:
    """
    Get current pod/host hostname.
    
    Priority:
    1. HOSTNAME environment variable (Kubernetes sets this)
    2. POD_NAME environment variable
    3. socket.gethostname()
    
    Returns:
        Hostname string
    """
    # Try environment variables first (Kubernetes sets HOSTNAME)
    hostname = os.getenv('HOSTNAME') or os.getenv('POD_NAME')
    if hostname:
        return hostname
    
    # Fallback to socket hostname
    try:
        return socket.gethostname()
    except Exception:
        return 'localhost'


def extract_host_from_server_id(server_id: str) -> str:
    """
    Extract a stable host segment from server_id.

    SOFA-JRaft often uses server_id like:
      "<group>/<pod>.<namespace>.svc.cluster.local:8181"
    For NDN name construction we must avoid '/' and ':port' leaking into a name component.
    
    Args:
        server_id: Server ID string (e.g., "pod-1.example.com" or "group/pod-1.ns.svc:8181")
    
    Returns:
        Host part (e.g., "pod-1")
    """
    if not server_id:
        return 'unknown'

    # Drop port if present
    base = server_id.split(':', 1)[0]
    # Drop group prefix if present (take last path segment)
    base = base.rsplit('/', 1)[-1]
    # Split by '.' and take the first DNS label
    parts = base.split('.', 1)
    host = parts[0] if parts else base
    return host or 'unknown'
