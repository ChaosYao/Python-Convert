# NDN Server for receiving Interest packets and sending Data packets (Transfer Proxy)
import asyncio
import base64
import json
import logging
import os
from typing import Optional
from ndn.app import NDNApp
from ndn.encoding import Name, FormalName, InterestParam
from ndn.security import KeychainSqlite3, TpmFile

from ..config import get_config
from ..grpc.client import SimpleClient
from ..grpc import bidirectional_pb2_grpc

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
                    # Only create directory if it doesn't exist
                    if pib_dir and not os.path.exists(pib_dir):
                        try:
                            os.makedirs(pib_dir, mode=0o700, exist_ok=True)
                            logger.info(f"Created PIB directory: {pib_dir}")
                        except PermissionError:
                            logger.warning(f"Permission denied when creating PIB directory: {pib_dir}, assuming it exists")
                    elif pib_dir and os.path.exists(pib_dir):
                        logger.debug(f"PIB directory already exists: {pib_dir}")
                
                if tpm_path:
                    tpm_path = os.path.expanduser(tpm_path)
                    tpm_path = os.path.abspath(tpm_path)
                    # tpm_path might be a file path, get its directory
                    tpm_dir = os.path.dirname(tpm_path)
                    # Only create directory if it doesn't exist
                    if tpm_dir and not os.path.exists(tpm_dir):
                        try:
                            os.makedirs(tpm_dir, mode=0o700, exist_ok=True)
                            logger.info(f"Created TPM directory: {tpm_dir}")
                        except PermissionError:
                            logger.warning(f"Permission denied when creating TPM directory: {tpm_dir}, assuming it exists")
                    elif tpm_dir and os.path.exists(tpm_dir):
                        logger.debug(f"TPM directory already exists: {tpm_dir}")
                
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
        
        # Initialize gRPC client if bridge is enabled.
        # The bridge must call the local JRaft process (upstream_raft, e.g. 127.0.0.1:8181)
        # directly, NOT the sidecar's own listen port (19090).  Calling the sidecar would
        # cause a loop: sidecar -> NDN Interest -> NDN server -> sidecar -> NDN Interest -> ...
        self.grpc_client: Optional[SimpleClient] = None
        if self.config.get_ndn_server_use_grpc():
            grpc_host = self.config.get_grpc_upstream_raft_addr()
            self.grpc_client = SimpleClient(server_address=grpc_host, config_path=config_path)
            self.grpc_client.connect()
            logger.info(f"gRPC client initialized for bridge (upstream JRaft): {grpc_host}")
    
    def _grpc_bridge_handler(self, name: FormalName, param: InterestParam, app_param: bytes) -> bytes:
        """Handler that bridges Interest to gRPC request."""
        name_str = Name.to_str(name)
        logger.info(f"gRPC bridge: Received Interest: {name_str}, app_param length: {len(app_param) if app_param else 0}")
        
        if self.grpc_client is None:
            error_msg = "gRPC client not initialized"
            logger.error(error_msg)
            return f"Error: {error_msg}".encode()
        
        try:
            from ..grpc import bidirectional_pb2
            from ..utils import extract_host_from_server_id
            
            # Check if this is a PullLogEntries request (starts with /raft/)
            if name_str.startswith("/raft/"):
                # Parse PullLogEntryRequest from app_param (content), not from interest name
                if not app_param:
                    logger.error("gRPC bridge: app_param is required for PullLogEntries request")
                    return json.dumps({'success': False, 'errorResponse': {'errorCode': 1, 'errorMsg': 'app_param is required'}}).encode()
                
                try:
                    # Parse JSON from app_param
                    if isinstance(app_param, memoryview):
                        raw_param = app_param.tobytes()
                    elif isinstance(app_param, bytes):
                        raw_param = app_param
                    else:
                        raw_param = bytes(app_param)
                    app_data = json.loads(raw_param.decode('utf-8'))
                    is_local_sidecar_interest = app_data.get('_origin') == 'grpc-sidecar'
                    logger.info(
                        "inbound_interest source=%s name=%s app_param_len=%d",
                        "local_grpc_sidecar" if is_local_sidecar_interest else "external_interest",
                        name_str,
                        len(raw_param),
                    )
                    



                    
                    # Reconstruct PullLogEntryRequest from app_param
                    grpc_request = bidirectional_pb2.PullLogEntryRequest()
                    grpc_request.group_id = app_data.get('group_id', '')
                    grpc_request.server_id = app_data.get('server_id', '')
                    grpc_request.peer_id = app_data.get('peer_id', '')
                    grpc_request.term = app_data.get('term', 0)
                    grpc_request.prev_log_term = app_data.get('prev_log_term', 0)
                    grpc_request.prev_log_index = app_data.get('prev_log_index', 0)
                    
                    logger.info(f"gRPC bridge: Sending PullLogEntries request to {self.grpc_client.server_address}")
                    import grpc
                    from ..grpc import bidirectional_pb2_grpc
                    channel = grpc.insecure_channel(self.grpc_client.server_address)
                    stub = bidirectional_pb2_grpc.SimpleServiceStub(channel)
                    grpc_response = stub.PullLogEntries(grpc_request)
                    channel.close()
                    
                    logger.info(f"gRPC bridge: Received PullLogEntryResponse: success={grpc_response.success}, term={grpc_response.term}")
            
                    # Convert PullLogEntryResponse to NDN Data content
                    data = {
                        'term': grpc_response.term,
                        'success': grpc_response.success,
                        'last_log_index': grpc_response.last_log_index,
                        'committed_index': grpc_response.committed_index,
                        'entries': []
                    }
                    
                    # Convert entries with full EntryMeta structure
                    for e in grpc_response.entries:
                        entry_data = {
                            'term': e.term,
                            'type': e.type,
                            'peers': list(e.peers),
                            'old_peers': list(e.old_peers),
                            'learners': list(e.learners),
                            'old_learners': list(e.old_learners)
                        }
                        if e.HasField('data_len'):
                            entry_data['data_len'] = e.data_len
                        if e.HasField('checksum'):
                            entry_data['checksum'] = e.checksum
                        data['entries'].append(entry_data)
                    
                    # Data field: encode bytes as base64 for JSON compatibility
                    if grpc_response.data:
                        data['data'] = base64.b64encode(grpc_response.data).decode('utf-8')
                    
                    # Error response (using errorCode and errorMsg)
                    if grpc_response.HasField('errorResponse'):
                        data['errorResponse'] = {
                            'errorCode': grpc_response.errorResponse.errorCode,
                            'errorMsg': grpc_response.errorResponse.errorMsg
                        }
                    content = json.dumps(data).encode()
                    logger.info(f"gRPC bridge: Converted PullLogEntryResponse to Data content, length: {len(content)} bytes")
                    return content
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.error(f"gRPC bridge: Failed to parse app_param: {e}")
                    return json.dumps({'success': False, 'errorResponse': {'errorCode': 1, 'errorMsg': f'Failed to parse app_param: {str(e)}'}}).encode()
            else:
                # Unknown Interest prefix, return error
                logger.warning(f"gRPC bridge: Unknown Interest prefix: {name_str}")
                return json.dumps({
                    'success': False,
                    'errorResponse': {
                        'errorCode': 4,
                        'errorMsg': f'Unknown Interest prefix: {name_str}'
                    }
                }).encode()
            
        except Exception as e:
            logger.error(f"gRPC bridge error: {e}", exc_info=True)
            return json.dumps({'success': False, 'errorResponse': {'errorCode': 3, 'errorMsg': str(e)}}).encode()
    
    async def register_route(self, prefix: str, use_grpc_bridge: Optional[bool] = None) -> bool:
        """
        Register a route for Interest handling.
        
        Only supports gRPC bridge mode: NDN Interest -> gRPC request -> gRPC response -> NDN Data
        
        Args:
            prefix: Interest prefix to register
            use_grpc_bridge: If True use gRPC bridge, if None use config

        Returns:
            True if NFD accepted the registration, False otherwise.
        """
        # Determine if gRPC bridge should be used
        if use_grpc_bridge is None:
            use_grpc_bridge = self.config.get_ndn_server_use_grpc()
        
        if not use_grpc_bridge or not self.grpc_client:
            # Still try to register the prefix so we can see explicit success/failure in logs.
            # Reply with a clear error so callers know the bridge is disabled.
            def not_configured_handler(name: FormalName, param: InterestParam, app_param: bytes):
                name_str = Name.to_str(name)
                logger.warning(f"Received Interest {name_str} but gRPC bridge is not configured")
                content = json.dumps({
                    'success': False,
                    'errorResponse': {
                        'errorCode': 5,
                        'errorMsg': 'gRPC bridge not configured'
                    }
                }).encode()
                freshness_period = self.config.get_server_config().get('freshness_period', 10000)
                self.app.put_data(name, content=content, freshness_period=freshness_period)

            try:
                ok = await self.app.register(prefix, not_configured_handler)
            except Exception as e:
                logger.error(f"Failed to register route to NFD: {prefix}. Error: {e}", exc_info=True)
                return False
            if ok:
                logger.info(f"Registered route to NFD: {prefix} (gRPC bridge disabled)")
            else:
                logger.error(f"Route registration to NFD returned False for prefix: {prefix}")
            return ok
        
        # Use gRPC bridge handler with optional prefix filtering.
        bridge_prefixes = self.config.get_ndn_server_grpc_bridge_prefixes()

        def grpc_bridge_handler(name: FormalName, param: InterestParam, app_param: bytes):
            name_str = Name.to_str(name)

            # Check if Interest name is in configured bridge prefixes
            in_bridge_prefixes = (not bridge_prefixes) or any(name_str.startswith(bp) for bp in bridge_prefixes)
            if not in_bridge_prefixes:
                logger.debug(f"Interest {name_str} not in bridge prefixes, ignoring")
                return

            # Translate to gRPC request (NDN -> gRPC)
            logger.info(f"Processing Interest with gRPC bridge: {name_str}")
            try:
                content = self._grpc_bridge_handler(name, param, app_param)
            except Exception as e:
                logger.error(f"gRPC bridge handler error: {e}", exc_info=True)
                content = json.dumps({
                    'success': False,
                    'errorResponse': {'errorCode': 3, 'errorMsg': str(e)}
                }).encode()

            logger.info(f"Sending Data: {name_str}, Content length: {len(content)} bytes")
            freshness_period = self.config.get_server_config().get('freshness_period', 10000)
            self.app.put_data(name, content=content, freshness_period=freshness_period)

        # Register to NFD with explicit success/failure result.
        try:
            ok = await self.app.register(prefix, grpc_bridge_handler)
        except Exception as e:
            logger.error(f"Failed to register route to NFD: {prefix}. Error: {e}", exc_info=True)
            return False

        if ok:
            logger.info(f"Registered route to NFD: {prefix} (mode: gRPC bridge - NDN -> gRPC)")
        else:
            logger.error(
                f"Route registration to NFD returned False for prefix: {prefix}. "
                f"This usually means NFD rejected the register command "
                f"(authorization/trust schema/management policy)."
            )
        return ok
    
    async def run(self, after_start=None):
        logger.info("Starting NDN server...")
        await self.app.run_forever(after_start=after_start)
    
    def shutdown(self):
        if self.grpc_client:
            self.grpc_client.disconnect()
            logger.info("gRPC client disconnected")
        if self.app:
            self.app.shutdown()

