# NDN Server for receiving Interest packets and sending Data packets (Transfer Proxy)
import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from ndn.app import NDNApp
from ndn.encoding import Name, FormalName, InterestParam
from ndn.security import KeychainSqlite3, TpmFile

from ..config import get_config
from ..grpc.client import SimpleClient
from ..grpc import bidirectional_pb2_grpc
from ..utils import extract_host_from_server_id, get_hostname
from ..grpc.jraft_codec import (
    PullLogEntryRequestLite,
    encode_pull_log_entry_request,
    decode_pull_log_entry_response,
)

# sofa-jraft gRPC method path for PullLogEntryRequest.
# GrpcClient.getCallMethod() generates: /<request.class.getName()>/_call
_JRAFT_PULL_LOG_METHOD = (
    "/com.alipay.sofa.jraft.rpc.RpcRequests$PullLogEntryRequest/_call"
)

# Max concurrent gRPC calls to the upstream JRaft node.
# Each worker thread handles one blocking gRPC call; keeping this bounded
# prevents overwhelming JRaft with too many simultaneous connections.
_BRIDGE_THREAD_POOL_SIZE = 4

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
                    tpm_dir = os.path.dirname(tpm_path)
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

        # Thread pool for blocking gRPC calls.
        # Runs _grpc_bridge_handler in worker threads so the asyncio event loop
        # (and therefore the NFD face / heartbeat) is never stalled.
        # put_data is always called back on the event loop via call_soon_threadsafe.
        self._bridge_executor = ThreadPoolExecutor(
            max_workers=_BRIDGE_THREAD_POOL_SIZE,
            thread_name_prefix="ndn-bridge",
        )

    def _grpc_bridge_handler(self, name: FormalName, param: InterestParam, app_param: bytes) -> bytes:
        """
        Bridge an NDN Interest to a gRPC call and return the response bytes.

        This is a plain synchronous method — it runs inside a ThreadPoolExecutor
        worker, completely off the asyncio event loop.  That keeps the event loop
        free to maintain the NFD face heartbeat at all times.
        """
        name_str = Name.to_str(name)
        logger.debug(f"gRPC bridge: Received Interest: {name_str}, app_param length: {len(app_param) if app_param else 0}")

        if self.grpc_client is None:
            error_msg = "gRPC client not initialized"
            logger.error(error_msg)
            return f"Error: {error_msg}".encode()

        try:
            if name_str.startswith("/raft/"):
                if not app_param:
                    logger.error("gRPC bridge: app_param is required for PullLogEntries request")
                    return json.dumps({'success': False, 'errorResponse': {'errorCode': 1, 'errorMsg': 'app_param is required'}}).encode()

                try:
                    if isinstance(app_param, memoryview):
                        raw_param = app_param.tobytes()
                    elif isinstance(app_param, bytes):
                        raw_param = app_param
                    else:
                        raw_param = bytes(app_param)
                    app_data = json.loads(raw_param.decode('utf-8'))
                    is_local_sidecar_interest = app_data.get('_origin') == 'grpc-sidecar'
                    logger.debug(
                        "inbound_interest source=%s name=%s app_param_len=%d",
                        "local_grpc_sidecar" if is_local_sidecar_interest else "external_interest",
                        name_str,
                        len(raw_param),
                    )

                    req_lite = PullLogEntryRequestLite(
                        group_id=app_data.get('group_id', ''),
                        server_id=app_data.get('server_id', ''),
                        peer_id=app_data.get('peer_id', ''),
                        term=app_data.get('term', 0),
                        prev_log_term=app_data.get('prev_log_term', 0),
                        prev_log_index=app_data.get('prev_log_index', 0),
                    )

                    req_bytes = encode_pull_log_entry_request(req_lite)
                    logger.debug(
                        "gRPC bridge: Sending PullLogEntries to %s via %s (%d bytes)",
                        self.grpc_client.server_address,
                        _JRAFT_PULL_LOG_METHOD,
                        len(req_bytes),
                    )

                    import grpc as _grpc
                    ch = _grpc.insecure_channel(self.grpc_client.server_address)
                    try:
                        stub = ch.unary_unary(
                            _JRAFT_PULL_LOG_METHOD,
                            request_serializer=lambda b: b,
                            response_deserializer=lambda b: b,
                        )
                        resp_bytes = stub(req_bytes)
                    finally:
                        ch.close()

                    data = decode_pull_log_entry_response(resp_bytes)
                    logger.debug(
                        "gRPC bridge: Received PullLogEntryResponse: success=%s term=%s",
                        data.get('success'), data.get('term'),
                    )
                    content = json.dumps(data).encode()
                    logger.debug(
                        "gRPC bridge: Converted PullLogEntryResponse to Data content, length: %d bytes",
                        len(content),
                    )
                    return content

                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.error(f"gRPC bridge: Failed to parse app_param: {e}")
                    return json.dumps({'success': False, 'errorResponse': {'errorCode': 1, 'errorMsg': f'Failed to parse app_param: {str(e)}'}}).encode()
            else:
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
        if use_grpc_bridge is None:
            use_grpc_bridge = self.config.get_ndn_server_use_grpc()

        if not use_grpc_bridge or not self.grpc_client:
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

        bridge_prefixes = self.config.get_ndn_server_grpc_bridge_prefixes()

        # Capture the running loop here (register_route runs inside run_forever's loop).
        # Worker threads use this reference to schedule put_data back on the event loop
        # via call_soon_threadsafe — the only thread-safe way to call python-ndn APIs.
        loop = asyncio.get_running_loop()

        def grpc_bridge_handler(name: FormalName, param: InterestParam, app_param: bytes):
            name_str = Name.to_str(name)

            in_bridge_prefixes = (not bridge_prefixes) or any(name_str.startswith(bp) for bp in bridge_prefixes)
            if not in_bridge_prefixes:
                logger.debug(f"Interest {name_str} not in bridge prefixes, ignoring")
                return

            logger.debug(f"Processing Interest with gRPC bridge: {name_str}")
            freshness_period = self.config.get_server_config().get('freshness_period', 10000)

            # Warn when all workers are busy — indicates JRaft backpressure.
            queued = self._bridge_executor._work_queue.qsize()
            active = self._bridge_executor._threads.__len__() if hasattr(self._bridge_executor, '_threads') else 0
            if queued > 0:
                logger.warning(
                    "ndn_bridge thread pool busy: queued=%d active_threads=%d (max=%d) interest=%s",
                    queued, active, _BRIDGE_THREAD_POOL_SIZE, name_str,
                )

            def _in_thread():
                try:
                    content = self._grpc_bridge_handler(name, param, app_param)
                except Exception as e:
                    logger.error(f"gRPC bridge handler error: {e}", exc_info=True)
                    content = json.dumps({
                        'success': False,
                        'errorResponse': {'errorCode': 3, 'errorMsg': str(e)}
                    }).encode()

                logger.debug(f"Sending Data: {name_str}, Content length: {len(content)} bytes")
                # call_soon_threadsafe schedules put_data on the event loop thread —
                # never call python-ndn APIs directly from a worker thread.
                loop.call_soon_threadsafe(
                    lambda: self.app.put_data(name, content=content, freshness_period=freshness_period)
                )

            self._bridge_executor.submit(_in_thread)

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

    # ------------------------------------------------------------------
    # Persistent face / route management
    # ------------------------------------------------------------------

    async def _nfdc(self, *args: str) -> str:
        """Run an nfdc command and return stdout. Errors are logged, not raised."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'nfdc', *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            out = stdout.decode(errors='replace').strip()
            err = stderr.decode(errors='replace').strip()
            if proc.returncode != 0:
                logger.warning("nfdc %s returned %d: %s", ' '.join(args), proc.returncode, err or out)
            return out
        except asyncio.TimeoutError:
            logger.error("nfdc %s timed out", ' '.join(args))
            return ''
        except FileNotFoundError:
            logger.error("nfdc not found in PATH; cannot manage NDN faces")
            return ''
        except Exception as e:
            logger.error("nfdc %s error: %s", ' '.join(args), e)
            return ''

    async def _ensure_persistent_face(self, uri: str) -> Optional[int]:
        out = await self._nfdc('face', 'create', uri, 'persistency', 'persistent')
        m = re.search(r'\bid=(\d+)\b', out)
        if m:
            return int(m.group(1))
        logger.error("Could not parse face id from nfdc output: %r", out)
        return None

    async def _ensure_route(self, prefix: str, face_id: int) -> None:
        await self._nfdc('route', 'add', prefix, str(face_id))

    async def setup_peer_faces(self) -> None:
        peers = self.config.get_ndn_peers()
        if not peers:
            logger.debug("No NDN peers configured; skipping face setup")
            return

        local_host = extract_host_from_server_id(get_hostname())
        for peer in peers:
            prefix = peer.get('prefix', '').strip()
            address = peer.get('address', '').strip()
            if not prefix or not address:
                logger.warning("Skipping invalid peer entry: %r", peer)
                continue
            peer_host = extract_host_from_server_id(prefix)
            if peer_host == local_host:
                logger.debug("Skipping self peer: %s", prefix)
                continue
            try:
                face_id = await self._ensure_persistent_face(address)
                if face_id is not None:
                    await self._ensure_route(prefix, face_id)
                    logger.info(
                        "NDN peer face ready: prefix=%s address=%s face_id=%d",
                        prefix, address, face_id,
                    )
                else:
                    logger.warning("Failed to create face for peer %s at %s", prefix, address)
            except Exception as e:
                logger.error("setup_peer_faces error for %s: %s", prefix, e, exc_info=True)

    async def run(self, after_start=None):
        logger.info("Starting NDN server...")
        await self.app.run_forever(after_start=after_start)

    def shutdown(self):
        self._bridge_executor.shutdown(wait=False)
        if self.grpc_client:
            self.grpc_client.disconnect()
            logger.info("gRPC client disconnected")
        if self.app:
            self.app.shutdown()
