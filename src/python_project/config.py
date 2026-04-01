"""
Configuration management for NDN/gRPC conversion project.

Supports loading configuration from:
1. YAML configuration file
2. Environment variables
3. Default values
"""
import os
import yaml
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class Config:
    """Configuration manager for the project."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Optional path to configuration file.
                        If None, searches for config.yaml in:
                        - Current directory
                        - Project root
                        - ~/.ndn/config.yaml
        """
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from file if it exists."""
        if self.config_path:
            config_file = Path(self.config_path)
        else:
            # Search for config.yaml in multiple locations
            possible_paths = [
                Path.cwd() / 'config.yaml',
                Path.cwd() / 'config.yml',
                Path(__file__).parent.parent.parent / 'config.yaml',
                Path(__file__).parent.parent.parent / 'config.yml',
                Path.home() / '.ndn' / 'config.yaml',
            ]
            
            config_file = None
            for path in possible_paths:
                if path.exists():
                    config_file = path
                    break
        
        if config_file and config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from: {config_file}")
                logger.info(f"Config content: {self._config}")
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")
                self._config = {}
        else:
            if self.config_path:
                logger.warning(f"Configuration file not found: {self.config_path}")
            else:
                logger.info("No configuration file found, using defaults and environment variables")
                logger.info(f"Searched paths: {possible_paths}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.
        
        Priority order:
        1. Environment variable (uppercase, underscores)
        2. Configuration file
        3. Default value
        
        Args:
            key: Configuration key (supports dot notation, e.g., 'ndn.pib_path')
            default: Default value if not found
            
        Returns:
            Configuration value
        """
        # First check environment variable
        env_key = key.upper().replace('.', '_')
        env_value = os.getenv(env_key)
        if env_value is not None:
            return env_value
        
        # Then check config file
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    break
            else:
                value = None
                break
        
        if value is not None:
            return value
        
        # Return default
        return default
    
    def get_ndn_pib_path(self) -> Optional[str]:
        """Get NDN PIB path from config or environment."""
        path = self.get('ndn.pib_path') or self.get('NDN_PIB_PATH')
        if path:
            # Expand ~ and relative paths
            path = os.path.expanduser(path)
            path = os.path.abspath(path)
        return path
    
    def get_ndn_tpm_path(self) -> Optional[str]:
        """Get NDN TPM path from config or environment."""
        path = self.get('ndn.tpm_path') or self.get('NDN_TPM_PATH')
        if path:
            # Expand ~ and relative paths
            path = os.path.expanduser(path)
            path = os.path.abspath(path)
        return path
    
    def get_log_level(self) -> str:
        """Get log level from config or environment."""
        return self.get('logging.level', 'INFO') or os.getenv('LOG_LEVEL', 'INFO')
    
    def get_server_config(self) -> Dict[str, Any]:
        """Get server-specific configuration."""
        return self._config.get('server', {})
    
    def get_client_config(self) -> Dict[str, Any]:
        """Get client-specific configuration."""
        return self._config.get('client', {})
    
    def get_client_disable_cache(self) -> bool:
        """Get disable_cache setting from client config."""
        return self.get('client.disable_cache', False)
    
    def get_grpc_config(self) -> Dict[str, Any]:
        return self._config.get('grpc', {})
    
    def get_grpc_server_port(self) -> int:
        port = self.get('grpc.server.port') or os.getenv('GRPC_SERVER_PORT')
        if port:
            return int(port)
        return 19090  # Default gRPC server port
    
    def get_grpc_client_host(self) -> str:
        """
        Address for gRPC client demos / tests.

        NOTE: the NDN server's Interest->gRPC bridge does NOT use this; it uses
        get_grpc_upstream_raft_addr() (127.0.0.1:8181) so that it calls JRaft
        directly instead of looping back through the sidecar.
        """
        host = self.get('grpc.client.host') or os.getenv('GRPC_CLIENT_HOST')
        if host:
            return host
        return 'localhost:19090'

    def get_ndn_peers(self) -> list:
        """
        Return list of peer NDN endpoints for persistent face/route setup.
        Each item: {'prefix': '/raft/raft-1', 'address': 'udp4://host:6363'}
        """
        peers = self._config.get('ndn', {}).get('peers', [])
        return peers if isinstance(peers, list) else []

    def get_ndn_face_refresh_interval(self) -> int:
        """Seconds between peer face/route refresh cycles (guards against NFD restart)."""
        v = self._config.get('ndn', {}).get('face_refresh_interval')
        if v is not None:
            return int(v)
        return int(os.getenv('NDN_FACE_REFRESH_INTERVAL', '60'))

    def get_grpc_upstream_raft_addr(self) -> str:
        """
        Same-pod JRaft gRPC (Java), bypassing this sidecar's listen port.

        Used when transparent forward has no peer_id/metadata (e.g. Cli GetLeaderRequest).
        Must NOT be the sidecar port or requests will loop back into this process.
        """
        h = self.get('grpc.server.upstream_raft') or os.getenv('GRPC_UPSTREAM_RAFT')
        if h:
            return h
        return '127.0.0.1:8181'
    
    def get_peer_sidecar_port(self) -> int:
        """
        Port used when forwarding to a remote peer's sidecar.

        When the sidecar derives a forward target from peer_id (e.g. raft-1:8181),
        it rewrites the port to this value (e.g. raft-1:19090) so that outbound
        traffic targets the peer's sidecar port instead of the JRaft port.
        This keeps all sidecar-to-sidecar communication on a port that is NOT
        covered by the iptables OUTPUT REDIRECT rule (which only matches APP_PORT /
        the JRaft port), preventing re-interception loops even when both processes
        run as uid=0.

        Override via env var PEER_SIDECAR_PORT.
        """
        v = self.get('grpc.server.peer_sidecar_port') or os.getenv('PEER_SIDECAR_PORT')
        if v:
            return int(v)
        return self.get_grpc_server_port()

    def get_grpc_forward_target(self) -> Optional[str]:
        """
        Get target gRPC server address for direct forwarding (without NDN conversion).
        If configured, requests will be forwarded directly to this server.
        Returns None if not configured (will use NDN conversion or return error).
        """
        target = self.get('grpc.server.forward_target') or os.getenv('GRPC_FORWARD_TARGET')
        if target:
            return target
        return None
    
    def get_grpc_forward_methods(self) -> list[str]:
        """
        Get list of RPC method names that should be forwarded (not converted to NDN).
        If empty, all methods (except those explicitly configured for NDN) will be forwarded.
        """
        methods = self.get('grpc.server.forward_methods', [])
        if not isinstance(methods, list):
            return []
        return [str(m) for m in methods if m]
    
    def should_forward_method(self, method_name: str) -> bool:
        """
        Determine if a method should be forwarded based on configuration.
        
        Rules:
        1. If forward_methods is configured and method is in the list -> forward
        2. If forward_methods is empty and forward_target is configured -> forward (default)
        3. Otherwise -> convert to NDN (if use_ndn is True)
        """
        forward_methods = self.get_grpc_forward_methods()
        forward_target = self.get_grpc_forward_target()
        
        # If forward_methods is explicitly configured
        if forward_methods:
            return method_name in forward_methods
        
        # If forward_target is configured but forward_methods is empty, forward all (except PullLogEntries if use_ndn)
        if forward_target:
            # If use_ndn is True, only forward non-PullLogEntries methods
            # If use_ndn is False, forward all
            use_ndn = self.get_grpc_server_use_ndn()
            if use_ndn:
                # Only forward methods that are not PullLogEntries
                return method_name != 'PullLogEntries'
            else:
                # Forward all methods
                return True
        
        # Default: don't forward (convert to NDN or return error)
        return False
    
    def get_grpc_test_data(self) -> list[tuple[int, str]]:
        test_data = self.get('grpc.test_data', [])
        if test_data:
            return [(item[0], item[1]) for item in test_data if len(item) >= 2]
        return [(1, "test1"), (2, "test2"), (3, "test3"), (4, "test4")]
    
    def get_grpc_server_use_ndn(self) -> bool:
        """Get whether gRPC server should use NDN client."""
        value = self.get('grpc.server.use_ndn')
        if value is None:
            return True  # Default to True for backward compatibility
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    
    def get_ndn_server_use_grpc(self) -> bool:
        """Get whether NDN server should use gRPC client for bridge."""
        value = self.get('grpc.bridge_enabled')
        if value is None:
            return False  # Default to False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    
    def get_ndn_server_grpc_bridge_prefixes(self) -> list[str]:
        """Get list of prefixes that should be forwarded to gRPC server."""
        prefixes = self.get('grpc.bridge_prefixes', [])
        if not isinstance(prefixes, list):
            return []
        return [str(p) for p in prefixes if p]


# Global config instance
_config_instance: Optional[Config] = None


def get_config(config_path: Optional[str] = None) -> Config:
    """
    Get or create global configuration instance.
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        Config instance
    """
    global _config_instance
    if _config_instance is None or config_path is not None:
        _config_instance = Config(config_path)
    return _config_instance

