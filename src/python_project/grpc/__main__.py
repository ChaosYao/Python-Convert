# gRPC module entry point
import os
import sys
import logging
from typing import Optional

from ..config import get_config
from ..utils import setup_logging
from .server import run_server

logger = logging.getLogger(__name__)


def get_mode(config_path: Optional[str] = None) -> str:
    """Get running mode. Defaults to 'server' mode."""
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode == 'server':
            return mode
    
    mode = os.getenv('MODE', '').lower()
    if mode == 'server':
        return mode
    
    config = get_config(config_path)
    mode = config.get_mode()
    if mode and mode.lower() == 'server':
        return mode.lower()
    
    return 'server'


def main():
    config_path = None
    
    if len(sys.argv) > 1 and sys.argv[1].startswith('--config='):
        config_path = sys.argv[1].split('=', 1)[1]
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    elif '--config' in sys.argv:
        idx = sys.argv.index('--config')
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]
            sys.argv = sys.argv[:idx] + sys.argv[idx + 2:]
    
    config = get_config(config_path)
    log_level = config.get_log_level()
    setup_logging(log_level)
    
    logger.info("gRPC Simple Demo")
    
    mode = get_mode(config_path)
    
    try:
        run_server(config_path=config_path)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    
    if False:  # Keep usage info for reference
        logger.info("Usage:")
        logger.info("  Command line: python -m python_project.grpc server [--config=path/to/config.yaml]")
        logger.info("  Environment:  MODE=server python -m python_project.grpc")
        logger.info("  Config file: Create config.yaml (see config.yaml)")
        logger.info("")
        logger.info("Modes:")
        logger.info("  server - Run gRPC server only")
        logger.info("")
        logger.info("Configuration Priority:")
        logger.info("  1. Command line arguments")
        logger.info("  2. Environment variables")
        logger.info("  3. Configuration file (config.yaml)")
        logger.info("  4. Default values")
        logger.info("")
        logger.info("gRPC Configuration in config.yaml:")
        logger.info("  grpc:")
        logger.info("    server:")
        logger.info("      port: 50051")
        logger.info("      use_ndn: true")
        logger.info("")
        logger.info("Environment Variables:")
        logger.info("  MODE: server")
        logger.info("  GRPC_SERVER_PORT: Server listening port")
        logger.info("  LOG_LEVEL: DEBUG|INFO|WARNING|ERROR|CRITICAL")
        logger.info("")
        logger.info("Examples:")
        logger.info("  python -m python_project.grpc server")
        logger.info("  python -m python_project.grpc server --config=my_config.yaml")
        logger.info("  MODE=server python -m python_project.grpc")
        logger.info("  GRPC_SERVER_PORT=8080 python -m python_project.grpc server")
        sys.exit(1)


if __name__ == '__main__':
    main()

