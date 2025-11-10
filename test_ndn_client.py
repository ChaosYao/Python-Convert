#!/usr/bin/env python3
# Test script for NDN client
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import asyncio
import logging
from python_project.ndn.client import NDNClient
from python_project.config import get_config
from python_project.utils import setup_logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_ndn_client():
    config = get_config()
    
    pib_path = config.get_ndn_pib_path()
    tpm_path = config.get_ndn_tpm_path()
    client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
    
    client_config = config.get_client_config()
    interests = client_config.get('interests', [])
    interest_lifetime = client_config.get('interest_lifetime', 4000)
    
    if not interests:
        logger.warning("No interests configured in config.yaml")
        logger.info("Please configure 'client.interests' in config.yaml")
        logger.info("Example: client.interests: ['/yao/test/demo/B']")
        return
    
    logger.info("=" * 50)
    logger.info("Testing NDN Client")
    logger.info("=" * 50)
    logger.info(f"Interests to send: {interests}")
    logger.info("Waiting 2 seconds for server to be ready...")
    await asyncio.sleep(2)
    
    logger.info("Sending Interest packets...")
    logger.info("=" * 50)
    
    for interest_name in interests:
        logger.info(f"\nSending Interest: {interest_name}")
        content = await client.express_interest(
            interest_name,
            lifetime=interest_lifetime
        )
        
        if content:
            logger.info(f"✓ Success! Received Data:")
            try:
                content_str = content.decode('utf-8')
                logger.info(f"  Content: {content_str}")
            except:
                logger.info(f"  Content (bytes): {content}")
        else:
            logger.warning(f"✗ Failed: No Data received for {interest_name}")
        
        await asyncio.sleep(1)
    
    logger.info("=" * 50)
    logger.info("Test completed")
    client.shutdown()


if __name__ == '__main__':
    try:
        asyncio.run(test_ndn_client())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

