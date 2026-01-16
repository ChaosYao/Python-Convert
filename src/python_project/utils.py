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
    Extract host part from server_id by splitting on '.' and taking the first part.
    
    Args:
        server_id: Server ID string (e.g., "pod-1.example.com" or "server-1.namespace.svc.cluster.local")
    
    Returns:
        Host part (e.g., "pod-1" or "server-1")
    """
    if not server_id:
        return 'unknown'
    
    # Split by '.' and take the first part
    parts = server_id.split('.')
    return parts[0] if parts else server_id
