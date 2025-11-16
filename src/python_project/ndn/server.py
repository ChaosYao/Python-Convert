# NDN Server for receiving Interest packets and sending Data packets
import asyncio
import logging
import os
from typing import Optional, Callable
from ndn.app import NDNApp
from ndn.encoding import Name, FormalName, InterestParam
from ndn.security import KeychainSqlite3, TpmFile

from ..config import get_config
from ..grpc.client import SimpleClient
from ..grpc.converter import grpc_data_to_data_content

logger = logging.getLogger(__name__)


class NDNServer:
    def __init__(
        self,
        app: Optional[NDNApp] = None,
        pib_path: Optional[str] = None,
        tpm_path: Optional[str] = None,
        config_path: Optional[str] = None
    ):
        self.config = get_config(config_path)
        
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
        
        # Initialize gRPC client if bridge is enabled
        self.grpc_client: Optional[SimpleClient] = None
        if self.config.get_ndn_server_use_grpc():
            grpc_host = self.config.get_grpc_client_host()
            self.grpc_client = SimpleClient(server_address=grpc_host, config_path=config_path)
            self.grpc_client.connect()
            logger.info(f"gRPC client initialized for bridge: {grpc_host}")
    
    def _grpc_bridge_handler(self, name: FormalName, param: InterestParam, app_param: bytes) -> bytes:
        """Handler that bridges Interest to gRPC request."""
        name_str = Name.to_str(name)
        logger.info(f"gRPC bridge: Received Interest: {name_str}, app_param length: {len(app_param) if app_param else 0}")
        
        if self.grpc_client is None:
            error_msg = "gRPC client not initialized"
            logger.error(error_msg)
            return f"Error: {error_msg}".encode()
        
        try:
            # Create gRPC request from Interest name
            from ..grpc import bidirectional_pb2
            grpc_request = bidirectional_pb2.Data(value=0, payload=name_str)
            logger.info(f"gRPC bridge: Using Interest name as payload: {name_str}")
            
            # Send gRPC request
            logger.info(f"gRPC bridge: Sending gRPC request to {self.grpc_client.server_address}")
            grpc_response = self.grpc_client.process_data(grpc_request.value, grpc_request.payload)
            logger.info(f"gRPC bridge: Received gRPC response: value={grpc_response.value}, payload={grpc_response.payload}")
            
            # Convert gRPC response to NDN Data content
            content = grpc_data_to_data_content(grpc_response)
            logger.info(f"gRPC bridge: Converted gRPC response to Data content, length: {len(content)} bytes")
            return content
            
        except Exception as e:
            logger.error(f"gRPC bridge error: {e}", exc_info=True)
            return f"Error: {str(e)}".encode()
    
    def register_route(self, prefix: str, handler: Optional[Callable] = None, use_grpc_bridge: Optional[bool] = None):
        """Register a route for Interest handling. Args: prefix (Interest prefix), handler (optional custom handler), use_grpc_bridge (if True use gRPC bridge, if None use config)."""
        # Determine if gRPC bridge should be used
        if use_grpc_bridge is None:
            use_grpc_bridge = self.config.get_ndn_server_use_grpc()
        
        def default_handler(name: FormalName, param: InterestParam, app_param: bytes):
            name_str = Name.to_str(name)
            logger.info(f"Received Interest: {name_str}, app_param length: {len(app_param) if app_param else 0}")
            
            if name_str in self.data_store:
                content = self.data_store[name_str]
            else:
                content = f"Data not found for {name_str}".encode()
                logger.warning(f"Data not found for {name_str}")
            
            logger.info(f"Sending Data: {name_str}, Content length: {len(content)} bytes")
            self.app.put_data(name, content=content, freshness_period=10000)
        
        if use_grpc_bridge and self.grpc_client:
            # Use gRPC bridge handler
            @self.app.route(prefix)
            def grpc_bridge_handler(name: FormalName, param: InterestParam, app_param: bytes):
                name_str = Name.to_str(name)
                logger.info(f"Processing Interest with gRPC bridge: {name_str}")
                try:
                    content = self._grpc_bridge_handler(name, param, app_param)
                except Exception as e:
                    logger.error(f"gRPC bridge handler error: {e}", exc_info=True)
                    content = f"Error: {e}".encode()
                
                logger.info(f"Sending Data: {name_str}, Content length: {len(content)} bytes")
                freshness_period = self.config.get_server_config().get('freshness_period', 10000)
                self.app.put_data(name, content=content, freshness_period=freshness_period)
        elif handler:
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
                freshness_period = self.config.get_server_config().get('freshness_period', 10000)
                self.app.put_data(name, content=content, freshness_period=freshness_period)
        else:
            self.app.route(prefix)(default_handler)
        
        mode_str = "gRPC bridge" if (use_grpc_bridge and self.grpc_client) else ("custom handler" if handler else "default")
        logger.info(f"Registered route: {prefix} (mode: {mode_str})")
    
    def store_data(self, name: str, content: bytes):
        self.data_store[name] = content
        logger.info(f"Stored data for: {name}")
    
    async def run(self):
        logger.info("Starting NDN server...")
        await self.app.run_forever()
    
    def shutdown(self):
        if self.grpc_client:
            self.grpc_client.disconnect()
            logger.info("gRPC client disconnected")
        if self.app:
            self.app.shutdown()

