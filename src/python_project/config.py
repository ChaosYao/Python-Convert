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
                logger.debug(f"Config content: {self._config}")
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")
                self._config = {}
        else:
            if self.config_path:
                logger.warning(f"Configuration file not found: {self.config_path}")
            else:
                logger.debug("No configuration file found, using defaults and environment variables")
                logger.debug(f"Searched paths: {possible_paths}")
    
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
        return self.get('ndn.pib_path') or self.get('NDN_PIB_PATH')
    
    def get_ndn_tpm_path(self) -> Optional[str]:
        """Get NDN TPM path from config or environment."""
        return self.get('ndn.tpm_path') or self.get('NDN_TPM_PATH')
    
    def get_log_level(self) -> str:
        """Get log level from config or environment."""
        return self.get('logging.level', 'INFO') or os.getenv('LOG_LEVEL', 'INFO')
    
    def get_mode(self) -> Optional[str]:
        """Get running mode from config or environment."""
        return self.get('mode') or os.getenv('MODE')
    
    def get_server_config(self) -> Dict[str, Any]:
        """Get server-specific configuration."""
        return self._config.get('server', {})
    
    def get_client_config(self) -> Dict[str, Any]:
        """Get client-specific configuration."""
        return self._config.get('client', {})


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

