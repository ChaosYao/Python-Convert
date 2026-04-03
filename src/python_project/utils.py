"""
Utility functions for the NDN/gRPC conversion project.
"""

import sys
import os
import socket
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


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


def parse_grpc_target_address(addr: str) -> Tuple[str, Optional[str]]:
    """
    Parse gRPC target "host:port" into host and port.

    Supports IPv4 ``host:port`` and bracketed IPv6 ``[::1]:port``.
    """
    addr = addr.strip()
    if not addr:
        return "", None
    if addr.startswith("["):
        end = addr.find("]")
        if end == -1:
            return addr, None
        host = addr[1:end]
        rest = addr[end + 1 :].lstrip()
        if rest.startswith(":") and rest[1:].isdigit():
            return host, rest[1:]
        return host, None
    if ":" in addr:
        host, maybe_port = addr.rsplit(":", 1)
        if maybe_port.isdigit():
            return host, maybe_port
    return addr, None


def collect_local_identity_hosts() -> List[str]:
    """
    Hostnames that may denote this pod (for loopback rewrite).

    Order: explicit override, Kubernetes pod name, container hostname, then socket.
    Set GRPC_SELF_HOSTNAME (comma-separated) or POD_NAME via downward API if HOSTNAME
    does not match your StatefulSet/pod DNS prefix (e.g. Docker sets a container id).
    """
    seen: set[str] = set()
    out: List[str] = []
    raw = os.getenv("GRPC_SELF_HOSTNAME")
    if raw:
        for part in raw.split(","):
            p = part.strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    for key in ("POD_NAME", "HOSTNAME"):
        v = os.getenv(key)
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    try:
        hn = socket.gethostname()
        if hn and hn not in seen:
            seen.add(hn)
            out.append(hn)
    except Exception:
        pass
    return out


def _target_host_refers_to_local(host: str, local_hostname: str) -> bool:
    """
    True if the gRPC target host denotes this machine (same sidecar / pod).

    Uses exact match (case-insensitive) or DNS parent/child relationship.
    When ``local_hostname`` is a single DNS label (typical K8s pod name), also
    matches peer FQDN whose first label equals it (e.g. raft-1 vs raft-1.raft.ns...).

    Does not use first-label match when ``local_hostname`` contains a dot (avoids
    ``a.b`` vs ``a.c`` false positives).
    """
    h = host.strip().lower()
    local = (local_hostname or "").strip().lower()
    if not h or not local:
        return False
    if h in ("localhost", "127.0.0.1", "::1"):
        return False
    if h == local:
        return True
    if h.startswith(local + "."):
        return True
    if local.startswith(h + "."):
        return True
    # K8s headless / peer_id: pod name "raft-1" vs "raft-1.raft-demo.svc..."
    if "." not in local and "." in h:
        if h.split(".")[0] == local:
            return True
    return False


def rewrite_target_to_localhost_if_self(target: str) -> str:
    """
    If target refers to this host (same sidecar / pod), rewrite host to localhost.

    Avoids forwarding loops when clients send this pod's hostname while the
    actual workload listens on loopback in the same network namespace.
    """
    host, port = parse_grpc_target_address(target)
    if not host:
        return target
    h = host.strip()
    if h in ("localhost", "127.0.0.1", "::1"):
        return target
    identities = collect_local_identity_hosts()
    if not identities:
        return target
    for local in identities:
        if _target_host_refers_to_local(h, local):
            out = f"localhost:{port}" if port else "localhost"
            logger.debug(
                "localhost_rewrite_check: MATCH target_host=%r port=%r identities=%r matched_identity=%r -> %r",
                h,
                port,
                identities,
                local,
                out,
            )
            return out
    return target
