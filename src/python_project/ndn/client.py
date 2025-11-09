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
from ndn.types import InterestNack, InterestTimeout

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
                # Expand ~ and relative paths
                if pib_path:
                    pib_path = os.path.expanduser(pib_path)
                    pib_path = os.path.abspath(pib_path)
                    # Create directory if it doesn't exist
                    pib_dir = os.path.dirname(pib_path)
                    if pib_dir and not os.path.exists(pib_dir):
                        os.makedirs(pib_dir, mode=0o700, exist_ok=True)
                        logger.info(f"Created PIB directory: {pib_dir}")
                
                if tpm_path:
                    tpm_path = os.path.expanduser(tpm_path)
                    tpm_path = os.path.abspath(tpm_path)
                    # Create directory if it doesn't exist
                    if not os.path.exists(tpm_path):
                        os.makedirs(tpm_path, mode=0o700, exist_ok=True)
                        logger.info(f"Created TPM directory: {tpm_path}")
                
                tpm = TpmFile(tpm_path) if tpm_path else TpmFile()
                pib_path = pib_path or os.path.join(os.path.expanduser('~'), '.ndn', 'pib.db')
                
                try:
                    keychain = KeychainSqlite3(pib_path, tpm)
                    self.app = NDNApp(keychain=keychain)
                    logger.info(f"Using custom PIB path: {pib_path}")
                    if tpm_path:
                        logger.info(f"Using custom TPM path: {tpm_path}")
                except Exception as e:
                    logger.error(f"Failed to initialize Keychain with PIB: {pib_path}, TPM: {tpm_path}")
                    logger.error(f"Error: {e}")
                    logger.error("Please check:")
                    logger.error(f"  1. Directory exists and is writable: {os.path.dirname(pib_path) if pib_path else 'N/A'}")
                    logger.error(f"  2. TPM directory exists and is writable: {tpm_path if tpm_path else 'N/A'}")
                    logger.error("  3. Or remove pib_path/tpm_path from config to use defaults")
                    raise
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
            
        except InterestNack as nack:
            # Handle NACK (Negative Acknowledgment)
            nack_code = int(nack)
            nack_messages = {
                100: "Congestion - Network is congested",
                150: "No Route - No forwarding path found (NFD cannot route this Interest)",
                151: "No Route - Forwarding hint is invalid",
                160: "No Route - No usable forwarding strategy",
            }
            message = nack_messages.get(nack_code, f"Unknown NACK code: {nack_code}")
            logger.error(f"Interest NACK received for '{name}': {message} (code: {nack_code})")
            
            if nack_code == 150:
                logger.error("=" * 60)
                logger.error("TROUBLESHOOTING: No Route (150)")
                logger.error("=" * 60)
                logger.error("Possible causes:")
                logger.error("  1. NFD (NDN Forwarding Daemon) is not running")
                logger.error("  2. No route registered in FIB for this prefix")
                logger.error("  3. Server is not running or not registered the route")
                logger.error("")
                logger.error("Solutions:")
                logger.error("  1. Check if NFD is running: nfd-status")
                logger.error("  2. Start NFD if not running: nfd-start")
                logger.error("  3. Register route in FIB: nfdc register <prefix> udp4://<server-ip>")
                logger.error("  4. Ensure server is running and registered the route")
                logger.error("=" * 60)
            
            return None
            
        except InterestTimeout:
            logger.error(f"Interest timeout for '{name}' (lifetime: {lifetime}ms)")
            logger.warning("Possible causes:")
            logger.warning("  1. Server is not responding")
            logger.warning("  2. Network latency is too high")
            logger.warning("  3. Interest lifetime is too short")
            return None
            
        except Exception as e:
            logger.error(f"Error expressing interest '{name}': {e}", exc_info=True)
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

