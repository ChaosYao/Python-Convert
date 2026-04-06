# NDN Client for sending Interest packets and receiving Data packets
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
    def __init__(
        self,
        app: Optional[NDNApp] = None,
        pib_path: Optional[str] = None,
        tpm_path: Optional[str] = None
    ):
        if app is not None:
            self.app = app
        else:
            pib_path = pib_path or os.getenv('NDN_PIB_PATH')
            tpm_path = tpm_path or os.getenv('NDN_TPM_PATH')
            
            if pib_path or tpm_path:
                if pib_path:
                    pib_path = os.path.expanduser(pib_path)
                    pib_path = os.path.abspath(pib_path)
                    pib_dir = os.path.dirname(pib_path)
                    if pib_dir and not os.path.exists(pib_dir):
                        os.makedirs(pib_dir, mode=0o700, exist_ok=True)
                        logger.info(f"Created PIB directory: {pib_dir}")
                
                if tpm_path:
                    tpm_path = os.path.expanduser(tpm_path)
                    tpm_path = os.path.abspath(tpm_path)
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
                logger.info("Using default PIB and TPM paths")
    
    async def express_interest(
        self,
        name: str,
        lifetime: int = 4000,
        can_be_prefix: bool = False,
        must_be_fresh: bool = False
    ) -> Optional[bytes]:
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
            logger.info(f"Content length: {len(content)} bytes")
            return bytes(content)
            
        except InterestNack as nack:
            try:
                nack_code = nack.args[0] if nack.args else int(str(nack))
            except (ValueError, TypeError, IndexError):
                nack_code = 150
            
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
    
    async def express_interest_with_params(
        self,
        name: str,
        app_param: bytes,
        lifetime: int = 4000,
        can_be_prefix: bool = False,
        must_be_fresh: bool = False
    ) -> Optional[bytes]:
        try:
            logger.info(f"Expressing Interest with params: {name}, param length: {len(app_param)}")
            data_name, meta_info, content = await self.app.express_interest(
                name=Name.from_str(name),
                interest_param=InterestParam(
                    lifetime=lifetime,
                    can_be_prefix=can_be_prefix,
                    must_be_fresh=must_be_fresh
                ),
                must_be_fresh=must_be_fresh,
                app_param=app_param
            )
            
            logger.info(f"Received Data: {Name.to_str(data_name)}")
            logger.info(f"Content length: {len(content)} bytes")
            return bytes(content)
            
        except InterestNack as nack:
            try:
                nack_code = nack.args[0] if nack.args else int(str(nack))
            except (ValueError, TypeError, IndexError):
                nack_code = 150
            logger.error(f"Interest NACK received for '{name}': code {nack_code}")
            return None
            
        except InterestTimeout:
            logger.error(f"Interest timeout for '{name}' (lifetime: {lifetime}ms)")
            return None
            
        except Exception as e:
            logger.error(f"Error expressing interest '{name}': {e}", exc_info=True)
            return None
    
    async def run(self, after_start=None):
        await self.app.run_forever(after_start=after_start)
    
    def shutdown(self):
        if self.app:
            self.app.shutdown()

