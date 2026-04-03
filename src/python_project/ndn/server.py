# NDN Server for receiving Interest packets and sending Data packets (Transfer Proxy)
import asyncio
import json
import logging
import os
import queue as _queue
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import grpc

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

# Timeout for each blocking gRPC call to JRaft.
# Under heavy write load the leader can be slow; cap the wait so worker
# threads are released promptly and the Interest pipeline stays moving.
_GRPC_CALL_TIMEOUT_SEC = 5.0

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
        # Persistent gRPC channel shared by all worker threads.
        # gRPC channels are thread-safe; reusing one channel eliminates the TCP
        # connection setup overhead that occurred with per-request channel creation.
        self._grpc_channel: Optional[grpc.Channel] = None
        self._pull_log_stub = None

        if self.config.get_ndn_server_use_grpc():
            grpc_host = self.config.get_grpc_upstream_raft_addr()
            self.grpc_client = SimpleClient(server_address=grpc_host, config_path=config_path)
            self.grpc_client.connect()
            self._grpc_channel = grpc.insecure_channel(grpc_host)
            self._pull_log_stub = self._grpc_channel.unary_unary(
                _JRAFT_PULL_LOG_METHOD,
                request_serializer=lambda b: b,
                response_deserializer=lambda b: b,
            )
            logger.info(f"gRPC client initialized for bridge (upstream JRaft): {grpc_host}")

        # Thread pool for blocking gRPC calls.
        # Worker threads make gRPC calls completely off the asyncio event loop,
        # then push completed (name, content) pairs into _result_queue.
        # The _drain_results() coroutine on the NDN event loop drains the queue
        # with an asyncio.sleep(0) yield between each put_data call, ensuring
        # the NFD face I/O is never starved by a burst of Data packets.
        self._bridge_executor = ThreadPoolExecutor(
            max_workers=_BRIDGE_THREAD_POOL_SIZE,
            thread_name_prefix="ndn-bridge",
        )

        # Thread-safe queue: worker threads push (name, content, freshness_period);
        # the NDN event loop drains it via _drain_results().
        self._result_queue: _queue.SimpleQueue = _queue.SimpleQueue()

        # asyncio Task for the drain loop; kept so it can be cancelled on shutdown.
        self._drain_task: Optional[asyncio.Task] = None

    def _grpc_bridge_handler(self, name: FormalName, param: InterestParam, app_param: bytes) -> bytes:
        """
        Bridge an NDN Interest to a gRPC call and return the response bytes.

        Runs inside a ThreadPoolExecutor worker — completely off the asyncio
        event loop.  Uses a persistent gRPC channel (thread-safe) to avoid
        TCP connection setup overhead on every request.
        """
        name_str = Name.to_str(name)
        logger.debug(f"gRPC bridge: Received Interest: {name_str}, app_param length: {len(app_param) if app_param else 0}")

        if self._pull_log_stub is None:
            error_msg = "gRPC stub not initialized"
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

                    t0 = time.monotonic()
                    try:
                        resp_bytes = self._pull_log_stub(req_bytes, timeout=_GRPC_CALL_TIMEOUT_SEC)
                    except grpc.RpcError as e:
                        elapsed = time.monotonic() - t0
                        logger.error(
                            "grpc_call_failed: name=%s elapsed=%.2fs status=%s details=%s",
                            name_str, elapsed, e.code(), e.details(),
                        )
                        raise
                    elapsed = time.monotonic() - t0
                    if elapsed > 1.0:
                        logger.warning(
                            "slow_grpc_call: name=%s elapsed=%.2fs (threshold=1s) "
                            "— JRaft may be under write load",
                            name_str, elapsed,
                        )
                    else:
                        logger.debug("grpc_call_ok: name=%s elapsed=%.3fs", name_str, elapsed)

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

    async def _drain_results(self) -> None:
        """
        Drain the gRPC result queue on the NDN event loop.

        Worker threads push (name, content, freshness_period) tuples into
        _result_queue after completing their gRPC calls.  This coroutine
        continuously drains that queue and calls put_data for each result.

        Isolation mechanism:
        - Between each put_data call, 'await asyncio.sleep(0)' yields control
          back to the event loop so NFD socket I/O (face keepalive, incoming
          Interests) is never starved by a burst of outgoing Data packets.
        - When the queue is empty a short sleep (1 ms) avoids a busy-spin while
          keeping response latency negligible.
        """
        logger.info("NDN result drain loop started")
        while True:
            try:
                name, content, freshness_period = self._result_queue.get_nowait()
            except _queue.Empty:
                # Queue empty — yield and poll again after 1 ms
                await asyncio.sleep(0.001)
                continue

            try:
                self.app.put_data(name, content=content, freshness_period=freshness_period)
                logger.debug("put_data ok: %s (%d bytes)", Name.to_str(name), len(content))
            except Exception as e:
                logger.error(
                    "put_data FAILED for %s — Interest will timeout: %s",
                    Name.to_str(name), e, exc_info=True,
                )

            # Yield after each Data packet so the event loop can service NFD
            # socket I/O (keepalive, incoming Interests) between sends.
            await asyncio.sleep(0)

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

        def grpc_bridge_handler(name: FormalName, param: InterestParam, app_param: bytes):
            """
            NDN Interest handler — runs on the event loop, must return immediately.

            Submits work to the thread pool and returns.  The worker thread makes
            the blocking gRPC call and pushes the result into _result_queue.
            The _drain_results() coroutine (also on this event loop) picks it up
            and calls put_data with asyncio.sleep(0) yields in between, so the
            NFD face I/O is never blocked by a burst of Data packets.
            """
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

                # Push result to queue — the drain coroutine calls put_data on
                # the event loop with inter-packet yields for face health.
                # Never call python-ndn APIs (put_data, etc.) from a worker thread.
                self._result_queue.put((name, content, freshness_period))
                logger.debug(f"Result queued for: {name_str}, {len(content)} bytes")

            self._bridge_executor.submit(_in_thread)

        try:
            ok = await self.app.register(prefix, grpc_bridge_handler)
        except Exception as e:
            logger.error(f"Failed to register route to NFD: {prefix}. Error: {e}", exc_info=True)
            return False

        if ok:
            logger.info(f"Registered route to NFD: {prefix} (mode: gRPC bridge - NDN -> gRPC)")
            # Start the drain loop as a long-running task on this event loop.
            # One drain task handles all prefixes; only start it once.
            if self._drain_task is None or self._drain_task.done():
                self._drain_task = asyncio.ensure_future(self._drain_results())
                logger.info("NDN result drain loop task created")
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
        # Cancel the drain task first so no more put_data calls are made
        if self._drain_task is not None and not self._drain_task.done():
            self._drain_task.cancel()
            logger.info("NDN result drain task cancelled")
        self._bridge_executor.shutdown(wait=False)
        if self._grpc_channel is not None:
            try:
                self._grpc_channel.close()
            except Exception:
                pass
            logger.info("gRPC channel closed")
        if self.grpc_client:
            self.grpc_client.disconnect()
            logger.info("gRPC client disconnected")
        if self.app:
            self.app.shutdown()
