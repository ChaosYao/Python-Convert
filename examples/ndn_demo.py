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

logger = logging.getLogger(__name__)


async def run_server():
    """Run NDN server that responds to Interests."""
    import os
    # Get PIB and TPM paths from environment variables
    pib_path = os.getenv('NDN_PIB_PATH')
    tpm_path = os.getenv('NDN_TPM_PATH')
    server = NDNServer(pib_path=pib_path, tpm_path=tpm_path)
    
    # Register route for '/example' prefix
    server.register_route('/example')
    
    # Store some sample data
    server.store_data('/example/data', b'Hello from NDN Server!')
    server.store_data('/example/test', b'This is a test message')
    
    logger.info("=" * 50)
    logger.info("NDN Server started")
    logger.info("Listening for Interests on prefix: /example")
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
    # Get PIB and TPM paths from environment variables
    pib_path = os.getenv('NDN_PIB_PATH')
    tpm_path = os.getenv('NDN_TPM_PATH')
    client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
    
    async def client_main():
        """Main client logic."""
        # Wait a bit for server to be ready
        await asyncio.sleep(2)
        
        logger.info("=" * 50)
        logger.info("NDN Client started")
        logger.info("Sending Interest packets...")
        logger.info("=" * 50)
        
        # Send Interest for '/example/data'
        content1 = await client.express_interest('/example/data')
        if content1:
            logger.info(f"Received content: {content1.decode()}")
        
        await asyncio.sleep(1)
        
        # Send Interest for '/example/test'
        content2 = await client.express_interest('/example/test')
        if content2:
            logger.info(f"Received content: {content2.decode()}")
        
        await asyncio.sleep(1)
        
        # Send Interest for non-existent data
        content3 = await client.express_interest('/example/notfound')
        if content3:
            logger.info(f"Received content: {content3.decode()}")
        
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

