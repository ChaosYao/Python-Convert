"""
NDN Server for receiving Interest packets and sending Data packets.
"""
import asyncio
import logging
import os
from typing import Optional, Callable
from ndn.app import NDNApp
from ndn.encoding import Name, FormalName, InterestParam
from ndn.security import KeychainSqlite3, TpmFile

logger = logging.getLogger(__name__)


class NDNServer:
    """NDN Server to receive Interest packets and send Data packets."""
    
    def __init__(
        self,
        app: Optional[NDNApp] = None,
        pib_path: Optional[str] = None,
        tpm_path: Optional[str] = None
    ):
        """
        Initialize NDN Server.
        
        Args:
            app: Optional NDNApp instance. If None, creates a new one.
            pib_path: Optional path to PIB (Public Information Base) database.
                     If None, uses default or environment variable NDN_PIB_PATH.
            tpm_path: Optional path to TPM (Trusted Platform Module) directory.
                     If None, uses default or environment variable NDN_TPM_PATH.
        """
        if app is not None:
            self.app = app
        else:
            # Get paths from environment variables if not provided
            pib_path = pib_path or os.getenv('NDN_PIB_PATH')
            tpm_path = tpm_path or os.getenv('NDN_TPM_PATH')
            
            # Create Keychain with custom paths if provided
            if pib_path or tpm_path:
                tpm = TpmFile(tpm_path) if tpm_path else TpmFile()
                pib_path = pib_path or os.path.join(os.path.expanduser('~'), '.ndn', 'pib.db')
                keychain = KeychainSqlite3(pib_path, tpm)
                self.app = NDNApp(keychain=keychain)
                logger.info(f"Using custom PIB path: {pib_path}")
                if tpm_path:
                    logger.info(f"Using custom TPM path: {tpm_path}")
            else:
                self.app = NDNApp()
                logger.debug("Using default PIB and TPM paths")
        
        self.data_store: dict[str, bytes] = {}
    
    def register_route(self, prefix: str, handler: Optional[Callable] = None):
        """
        Register a route to handle Interests with a given prefix.
        
        Args:
            prefix: Name prefix to register (e.g., '/example')
            handler: Optional handler function that takes (name, param, app_param).
                     If None, uses default handler that returns data from data_store.
        """
        def default_handler(name: FormalName, param: InterestParam, app_param: bytes):
            """Default handler that looks up data in data_store."""
            name_str = Name.to_str(name)
            logger.info(f"Received Interest: {name_str}")
            
            if name_str in self.data_store:
                content = self.data_store[name_str]
            else:
                # Return a default message if not found
                content = f"Data not found for {name_str}".encode()
                logger.warning(f"Data not found for {name_str}")
            
            # Send Data packet
            logger.info(f"Sending Data: {name_str}, Content length: {len(content)} bytes")
            self.app.put_data(name, content=content, freshness_period=10000)
        
        if handler:
            @self.app.route(prefix)
            def interest_handler(name: FormalName, param: InterestParam, app_param: bytes):
                """Handle incoming Interest with custom handler."""
                name_str = Name.to_str(name)
                logger.info(f"Received Interest: {name_str}")
                try:
                    content = handler(name, param, app_param)
                    if not isinstance(content, bytes):
                        content = str(content).encode()
                except Exception as e:
                    logger.error(f"Handler error: {e}", exc_info=True)
                    content = f"Error: {e}".encode()
                
                logger.info(f"Sending Data: {name_str}, Content length: {len(content)} bytes")
                self.app.put_data(name, content=content, freshness_period=10000)
        else:
            self.app.route(prefix)(default_handler)
        
        logger.info(f"Registered route: {prefix}")
    
    def store_data(self, name: str, content: bytes):
        """
        Store data for a given name.
        
        Args:
            name: Name to store data under
            content: Content bytes to store
        """
        self.data_store[name] = content
        logger.info(f"Stored data for: {name}")
    
    async def run(self):
        """Run the NDN server app."""
        logger.info("Starting NDN server...")
        await self.app.run_forever()
    
    def shutdown(self):
        """Shutdown the server."""
        if self.app:
            self.app.shutdown()

