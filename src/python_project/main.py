"""
Main entry point for NDN/gRPC conversion project.

Supports running in server or client mode via:
1. Command line argument: python -m python_project server|client
2. Environment variable: MODE=server|client
3. Configuration file: config.yaml
"""
import asyncio
import os
import sys
import logging
from typing import Optional

from .ndn.client import NDNClient
from .ndn.server import NDNServer
from .utils import setup_logging
from .config import get_config

logger = logging.getLogger(__name__)


def get_mode(config_path: Optional[str] = None) -> Optional[str]:
    """
    Get the running mode (server or client) from various sources.
    
    Priority order:
    1. Command line argument
    2. Environment variable MODE
    3. Configuration file
    4. None (will show usage)
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        'server', 'client', or None
    """
    # Check command line argument
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode in ['server', 'client']:
            return mode
    
    # Check environment variable
    mode = os.getenv('MODE', '').lower()
    if mode in ['server', 'client']:
        return mode
    
    # Check configuration file
    config = get_config(config_path)
    mode = config.get_mode()
    if mode and mode.lower() in ['server', 'client']:
        return mode.lower()
    
    return None


def run_server(config_path: Optional[str] = None):
    """Run NDN server that responds to Interests."""
    config = get_config(config_path)
    
    # Get PIB and TPM paths from config
    pib_path = config.get_ndn_pib_path()
    tpm_path = config.get_ndn_tpm_path()
    server = NDNServer(pib_path=pib_path, tpm_path=tpm_path)
    
    # Get server configuration
    server_config = config.get_server_config()
    routes = server_config.get('routes', [])
    data = server_config.get('data', {})
    
    # Log configuration for debugging
    logger.debug(f"Server config loaded: {server_config}")
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


def run_client(config_path: Optional[str] = None):
    """Run NDN client that sends Interests."""
    config = get_config(config_path)
    
    # Get PIB and TPM paths from config
    pib_path = config.get_ndn_pib_path()
    tpm_path = config.get_ndn_tpm_path()
    client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
    
    # Get client configuration
    client_config = config.get_client_config()
    interests = client_config.get('interests', [])
    interest_lifetime = client_config.get('interest_lifetime', 4000)
    
    # Log configuration for debugging
    logger.debug(f"Client config loaded: {client_config}")
    
    # Warn if no interests configured
    if not interests:
        logger.warning("No interests configured in config file! Client will not send any Interests.")
        logger.warning("Please configure 'client.interests' in config.yaml")
        logger.info("Example: client.interests: ['/yao/test/demo/B']")
    else:
        logger.info(f"Will send {len(interests)} interests: {interests}")
    
    async def client_main():
        """Main client logic."""
        # Wait a bit for server to be ready
        await asyncio.sleep(2)
        
        logger.info("=" * 50)
        logger.info("NDN Client started")
        
        if not interests:
            logger.warning("No interests to send. Exiting.")
            client.shutdown()
            return
        
        logger.info("Sending Interest packets...")
        logger.info("=" * 50)
        
        # Send Interests from configuration
        for interest_name in interests:
            content = await client.express_interest(
                interest_name,
                lifetime=interest_lifetime
            )
            if content:
                logger.info(f"Received content: {content.decode()}")
            await asyncio.sleep(1)
        
        logger.info("Demo completed")
        client.shutdown()
    
    try:
        # NDNApp.run_forever() handles event loop internally, so we call it directly
        client.app.run_forever(after_start=client_main())
    except KeyboardInterrupt:
        logger.info("Shutting down client...")
        client.shutdown()


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
    
    # Get mode from various sources
    mode = get_mode(config_path)
    
    if mode == 'server':
        try:
            # run_server() calls app.run_forever() which handles event loop internally
            run_server(config_path)
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
    elif mode == 'client':
        try:
            # run_client() calls app.run_forever() which handles event loop internally
            run_client(config_path)
        except KeyboardInterrupt:
            logger.info("Client stopped by user")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
    else:
        logger.info("Usage:")
        logger.info("  Command line: python -m python_project [server|client] [--config=path/to/config.yaml]")
        logger.info("  Environment:  MODE=server|client python -m python_project")
        logger.info("  Config file: Create config.yaml (see config.yaml.example)")
        logger.info("")
        logger.info("Configuration Priority:")
        logger.info("  1. Command line arguments")
        logger.info("  2. Environment variables")
        logger.info("  3. Configuration file (config.yaml)")
        logger.info("  4. Default values")
        logger.info("")
        logger.info("Configuration File:")
        logger.info("  - Copy config.yaml.example to config.yaml")
        logger.info("  - Configure PIB/TPM paths, routes, data, etc.")
        logger.info("  - Or use --config=/path/to/config.yaml to specify custom location")
        logger.info("")
        logger.info("Environment Variables:")
        logger.info("  MODE: server|client")
        logger.info("  NDN_PIB_PATH: Path to PIB database")
        logger.info("  NDN_TPM_PATH: Path to TPM directory")
        logger.info("  LOG_LEVEL: DEBUG|INFO|WARNING|ERROR|CRITICAL")
        logger.info("")
        logger.info("Examples:")
        logger.info("  python -m python_project server")
        logger.info("  python -m python_project client --config=my_config.yaml")
        logger.info("  MODE=server python -m python_project")
        logger.info("  NDN_PIB_PATH=/path/to/pib.db python -m python_project server")
        sys.exit(1)


if __name__ == '__main__':
    main()
