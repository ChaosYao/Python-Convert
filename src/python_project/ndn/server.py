# NDN Server for receiving Interest packets and sending Data packets
import asyncio
import logging
import os
from typing import Optional, Callable
from ndn.app import NDNApp
from ndn.encoding import Name, FormalName, InterestParam
from ndn.security import KeychainSqlite3, TpmFile

logger = logging.getLogger(__name__)

try:
    from ..grpc.client import SimpleClient
    from ..grpc.converter import data_content_to_grpc_data, grpc_data_to_data_content
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    logger.warning("gRPC module not available, NDN-to-gRPC conversion disabled")


class NDNServer:
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
        
        self.data_store: dict[str, bytes] = {}
        self.grpc_client: Optional[SimpleClient] = None
        self.grpc_enabled = False
    
    def enable_grpc_bridge(self, grpc_server_address: Optional[str] = None):
        if not GRPC_AVAILABLE:
            logger.warning("gRPC not available, bridge disabled")
            return
        
        from ..config import get_config
        config = get_config()
        
        if grpc_server_address is None:
            grpc_server_address = config.get_grpc_client_host()
        
        self.grpc_client = SimpleClient(server_address=grpc_server_address)
        self.grpc_client.connect()
        self.grpc_enabled = True
        logger.info(f"NDN-to-gRPC bridge enabled, connecting to {grpc_server_address}")
    
    def register_route(self, prefix: str, handler: Optional[Callable] = None):
        def default_handler(name: FormalName, param: InterestParam, app_param: bytes):
            name_str = Name.to_str(name)
            logger.info(f"Received Interest: {name_str}, app_param length: {len(app_param) if app_param else 0}")
            
            if self.grpc_enabled and app_param:
                logger.info(f"Converting Interest app_param to gRPC request")
                try:
                    grpc_request = data_content_to_grpc_data(app_param)
                    logger.info(f"Calling gRPC server: value={grpc_request.value}, payload={grpc_request.payload}")
                    
                    grpc_response = self.grpc_client.process_data(grpc_request.value, grpc_request.payload)
                    
                    content = grpc_data_to_data_content(grpc_response)
                    logger.info(f"Received gRPC response, converted to Data: value={grpc_response.value}, payload={grpc_response.payload}")
                except Exception as e:
                    logger.error(f"Error in gRPC bridge: {e}", exc_info=True)
                    content = f"gRPC error: {str(e)}".encode()
            elif name_str in self.data_store:
                content = self.data_store[name_str]
            else:
                content = f"Data not found for {name_str}".encode()
                logger.warning(f"Data not found for {name_str}")
            
            logger.info(f"Sending Data: {name_str}, Content length: {len(content)} bytes")
            self.app.put_data(name, content=content, freshness_period=10000)
        
        if handler:
            @self.app.route(prefix)
            def interest_handler(name: FormalName, param: InterestParam, app_param: bytes):
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
        self.data_store[name] = content
        logger.info(f"Stored data for: {name}")
    
    async def run(self):
        logger.info("Starting NDN server...")
        await self.app.run_forever()
    
    def shutdown(self):
        if self.grpc_client:
            self.grpc_client.disconnect()
        if self.app:
            self.app.shutdown()

