"""
NDN Client for sending Interest packets and receiving Data packets.
"""
import asyncio
import logging
import os
from typing import Optional
from ndn.app import NDNApp
from ndn.encoding import Name, InterestParam, FormalName
from ndn.security import KeychainSqlite3, TpmFile

logger = logging.getLogger(__name__)


class NDNClient:
    """NDN Client to send Interest packets and receive Data packets."""
    
    def __init__(
        self,
        app: Optional[NDNApp] = None,
        pib_path: Optional[str] = None,
        tpm_path: Optional[str] = None
    ):
        """
        Initialize NDN Client.
        
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
    
    async def express_interest(
        self,
        name: str,
        lifetime: int = 4000,
        can_be_prefix: bool = False,
        must_be_fresh: bool = False
    ) -> Optional[bytes]:
        """
        Express an Interest packet and wait for Data packet.
        
        Args:
            name: Name of the Interest (e.g., '/example/data')
            lifetime: Interest lifetime in milliseconds
            can_be_prefix: Whether the name can be a prefix
            must_be_fresh: Whether the Data must be fresh
            
        Returns:
            Content bytes from Data packet, or None if failed
        """
        try:
            logger.info(f"Expressing Interest: {name}")
            data_name, meta_info, content = await self.app.express_interest(
                name=Name.from_str(name),
                interest_param=InterestParam(
                    lifetime=lifetime,
                    can_be_prefix=can_be_prefix,
                    must_be_fresh=must_be_fresh
                ),
                must_be_fresh=must_be_fresh
            )
            
            logger.info(f"Received Data: {Name.to_str(data_name)}")
            logger.debug(f"Content length: {len(content)} bytes")
            return bytes(content)
            
        except Exception as e:
            logger.error(f"Error expressing interest: {e}", exc_info=True)
            return None
    
    async def run(self, after_start=None):
        """
        Run the NDN client app.
        
        Args:
            after_start: Optional coroutine to run after app starts
        """
        await self.app.run_forever(after_start=after_start)
    
    def shutdown(self):
        """Shutdown the client."""
        if self.app:
            self.app.shutdown()

