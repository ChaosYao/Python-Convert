"""
Minimal demo for NDN Interest/Data packet communication.

This demo shows:
1. Server receiving Interest packets and sending Data packets
2. Client sending Interest packets and receiving Data packets

Usage:
    # Terminal 1: Run server
    python examples/ndn_demo.py server
    
    # Terminal 2: Run client
    python examples/ndn_demo.py client
"""
import asyncio
import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

from python_project.ndn.client import NDNClient
from python_project.ndn.server import NDNServer
from python_project.utils import setup_logging
from python_project.config import get_config

logger = logging.getLogger(__name__)


async def run_server():
    """Run NDN server that responds to Interests."""
    import os
    # Try to load config file
    config = get_config()
    
    # Get PIB and TPM paths from config or environment
    pib_path = config.get_ndn_pib_path() or os.getenv('NDN_PIB_PATH')
    tpm_path = config.get_ndn_tpm_path() or os.getenv('NDN_TPM_PATH')
    server = NDNServer(pib_path=pib_path, tpm_path=tpm_path)
    
    # Get server configuration
    server_config = config.get_server_config()
    routes = server_config.get('routes', [])
    data = server_config.get('data', {})
    
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
        await server.run()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        server.shutdown()


async def run_client():
    """Run NDN client that sends Interests."""
    import os
    # Try to load config file
    config = get_config()
    
    # Get PIB and TPM paths from config or environment
    pib_path = config.get_ndn_pib_path() or os.getenv('NDN_PIB_PATH')
    tpm_path = config.get_ndn_tpm_path() or os.getenv('NDN_TPM_PATH')
    client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
    
    # Get client configuration
    client_config = config.get_client_config()
    interests = client_config.get('interests', [])
    interest_lifetime = client_config.get('interest_lifetime', 4000)
    
    # Warn if no interests configured
    if not interests:
        logger.warning("No interests configured in config file! Client will not send any Interests.")
        logger.warning("Please configure 'client.interests' in config.yaml")
        logger.info("Example: client.interests: ['/yao/test/demo/B']")
    
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
        
        logger.info(f"Sending {len(interests)} Interest packets: {interests}")
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
        await client.run(after_start=client_main())
    except KeyboardInterrupt:
        logger.info("Shutting down client...")
        client.shutdown()


if __name__ == '__main__':
    # Setup logging
    setup_logging("INFO")
    
    logger.info("NDN Interest/Data Demo")
    logger.info("Note: This demo requires NDN network to be running.")
    logger.info("For local testing, you may need to set up NFD (NDN Forwarding Daemon).")
    
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode == 'server':
            try:
                asyncio.run(run_server())
            except KeyboardInterrupt:
                logger.info("Server stopped by user")
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
        elif mode == 'client':
            try:
                asyncio.run(run_client())
            except KeyboardInterrupt:
                logger.info("Client stopped by user")
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
        else:
            logger.error(f"Unknown mode: {mode}")
            logger.info("Usage: python examples/ndn_demo.py [server|client]")
    else:
        logger.info("Usage: python examples/ndn_demo.py [server|client]")
        logger.info("Run 'server' in one terminal and 'client' in another terminal.")

