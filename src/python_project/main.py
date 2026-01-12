"""
Main entry point for NDN/gRPC conversion project (Sidecar mode).

Supports running in:
- sidecar mode: both gRPC Server and NDN Server (default)
- server mode: NDN Server only

Configuration via:
1. Command line argument: python -m python_project [server|sidecar]
2. Environment variable: MODE=server|sidecar
3. Configuration file: config.yaml
"""
import asyncio
import os
import sys
import logging
import threading
from typing import Optional

from .ndn.server import NDNServer
from .utils import setup_logging
from .config import get_config

logger = logging.getLogger(__name__)


def get_mode(config_path: Optional[str] = None) -> Optional[str]:
    """Get running mode. Returns 'sidecar' by default."""
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode in ['server', 'sidecar']:
            return mode
    
    mode = os.getenv('MODE', '').lower()
    if mode in ['server', 'sidecar']:
        return mode
    
    config = get_config(config_path)
    mode = config.get_mode()
    if mode and mode.lower() in ['server', 'sidecar']:
        return mode.lower()
    
    # Default to sidecar mode
    return 'sidecar'


def run_server(config_path: Optional[str] = None):
    """Run NDN server that responds to Interests."""
    config = get_config(config_path)
    
    # Get PIB and TPM paths from config
    pib_path = config.get_ndn_pib_path()
    tpm_path = config.get_ndn_tpm_path()
    server = NDNServer(pib_path=pib_path, tpm_path=tpm_path, config_path=config_path)
    
    server_config = config.get_server_config()
    routes = server_config.get('routes', [])
    data = server_config.get('data', {})
    
    # Log configuration for debugging
    logger.info(f"Server config loaded: {server_config}")
    logger.info(f"Routes to register: {routes}")
    logger.info(f"Data to store: {list(data.keys())}")
    
    # Warn if no routes configured
    if not routes:
        logger.warning("No routes configured in config file! Server will not respond to any Interests.")
        logger.warning("Please configure 'server.routes' in config.yaml")
    else:
        # Register routes
        for route in routes:
            server.register_route(route)
    
    # Warn if no data configured
    if not data:
        logger.warning("No data configured in config file!")
        logger.warning("Please configure 'server.data' in config.yaml")
    else:
        # Store data
        for name, content in data.items():
            if isinstance(content, str):
                content = content.encode()
            server.store_data(name, content)
    
    logger.info("=" * 50)
    logger.info("NDN Server started")
    if routes:
        logger.info(f"Listening for Interests on prefixes: {', '.join(routes)}")
    else:
        logger.info("No routes registered - server will not respond to Interests")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)
    
    try:
        # NDNApp.run_forever() handles event loop internally, so we call it directly
        server.app.run_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        server.shutdown()


def run_sidecar(config_path: Optional[str] = None):
    """
    Run sidecar mode: both gRPC Server and NDN Server running concurrently.
    
    Thread safety:
    - NDN Server runs in its own thread with its own NDNApp instance
    - NDN Client (for gRPC Server) runs in its own thread with its own NDNApp instance
    - gRPC Server runs in async event loop
    """
    config = get_config(config_path)
    
    from .grpc.server import run_server_async
    
    pib_path = config.get_ndn_pib_path()
    tpm_path = config.get_ndn_tpm_path()
    
    # Initialize NDN Server
    ndn_server = NDNServer(pib_path=pib_path, tpm_path=tpm_path, config_path=config_path)
    
    # Configure NDN Server routes and data
    server_config = config.get_server_config()
    routes = server_config.get('routes', [])
    data = server_config.get('data', {})
    
    logger.info(f"Routes to register: {routes}")
    logger.info(f"Data to store: {list(data.keys())}")
    
    if not routes:
        logger.warning("No routes configured in config file!")
    else:
        for route in routes:
            ndn_server.register_route(route)
    
    if not data:
        logger.warning("No data configured in config file!")
    else:
        for name, content in data.items():
            if isinstance(content, str):
                content = content.encode()
            ndn_server.store_data(name, content)
    
    # Start NDN Server in its own thread (thread-safe)
    def run_ndn_server_thread():
        """Run NDN Server in dedicated thread."""
        try:
            logger.info("NDN Server thread started")
            ndn_server.app.run_forever()
        except Exception as e:
            logger.error(f"NDN Server error: {e}", exc_info=True)
        finally:
            ndn_server.shutdown()
    
    ndn_server_thread = threading.Thread(target=run_ndn_server_thread, daemon=True)
    ndn_server_thread.start()
    
    logger.info("=" * 50)
    logger.info("Sidecar mode started")
    logger.info(f"gRPC Server: port {config.get_grpc_server_port()}")
    if routes:
        logger.info(f"NDN Server: listening on prefixes {', '.join(routes)}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)
    
    # Run gRPC Server in async event loop (main thread)
    try:
        asyncio.run(run_server_async(port=None, config_path=config_path))
    except KeyboardInterrupt:
        logger.info("Shutting down sidecar...")
        ndn_server.shutdown()
        logger.info("Sidecar stopped")


def run_both_servers(config_path: Optional[str] = None):
    """Legacy function, redirects to run_sidecar."""
    logger.warning("run_both_servers is deprecated, using run_sidecar instead")
    run_sidecar(config_path)




def main():
    """Main entry point."""
    # Check for config file path in command line
    config_path = None
    if len(sys.argv) > 1 and sys.argv[1].startswith('--config='):
        config_path = sys.argv[1].split('=', 1)[1]
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    elif '--config' in sys.argv:
        idx = sys.argv.index('--config')
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]
            sys.argv = sys.argv[:idx] + sys.argv[idx + 2:]
    
    # Get config and setup logging
    config = get_config(config_path)
    log_level = config.get_log_level()
    setup_logging(log_level)
    
    logger.info("NDN Interest/Data Demo")
    logger.info("Note: This demo requires NDN network to be running.")
    logger.info("For local testing, you may need to set up NFD (NDN Forwarding Daemon).")
    
    mode = get_mode(config_path)
    
    if mode == 'server':
        try:
            run_server(config_path)
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
    elif mode == 'sidecar':
        try:
            run_sidecar(config_path)
        except KeyboardInterrupt:
            logger.info("Sidecar stopped by user")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
    else:
        logger.info("Usage:")
        logger.info("  Command line: python -m python_project [server|sidecar] [--config=path/to/config.yaml]")
        logger.info("  Environment:  MODE=server|sidecar python -m python_project")
        logger.info("  Config file: Create config.yaml (see config.yaml.example)")
        logger.info("")
        logger.info("Modes:")
        logger.info("  server  - Run NDN server only")
        logger.info("  sidecar - Run both gRPC server and NDN server (default)")
        logger.info("")
        logger.info("Configuration Priority:")
        logger.info("  1. Command line arguments")
        logger.info("  2. Environment variables")
        logger.info("  3. Configuration file (config.yaml)")
        logger.info("  4. Default values (sidecar mode)")
        logger.info("")
        logger.info("Configuration File:")
        logger.info("  - Copy config.yaml.example to config.yaml")
        logger.info("  - Configure PIB/TPM paths, routes, data, etc.")
        logger.info("  - Or use --config=/path/to/config.yaml to specify custom location")
        logger.info("")
        logger.info("Environment Variables:")
        logger.info("  MODE: server|sidecar")
        logger.info("  NDN_PIB_PATH: Path to PIB database")
        logger.info("  NDN_TPM_PATH: Path to TPM directory")
        logger.info("  LOG_LEVEL: DEBUG|INFO|WARNING|ERROR|CRITICAL")
        logger.info("")
        logger.info("Examples:")
        logger.info("  python -m python_project           # Start sidecar mode (default)")
        logger.info("  python -m python_project server    # Start NDN server only")
        logger.info("  python -m python_project sidecar   # Start sidecar mode")
        logger.info("  MODE=sidecar python -m python_project   # Start sidecar mode")
        sys.exit(1)


if __name__ == '__main__':
    main()
