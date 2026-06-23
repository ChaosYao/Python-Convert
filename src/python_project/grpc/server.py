# gRPC simple server implementation
import asyncio
import logging
import threading
import os
from queue import Queue
from dataclasses import dataclass
from concurrent.futures import Future
from typing import Optional

import grpc

from ..config import get_config
from ..ndn.client import NDNClient
from ..utils import (
    collect_local_identity_hosts,
    parse_grpc_target_address,
    rewrite_target_to_localhost_if_self,
)
from . import bidirectional_pb2
from . import bidirectional_pb2_grpc
from .jraft_codec import (
    decode_pull_log_entry_request,
    encode_pull_log_entry_response_from_ndn_content,
    extract_string_field,
    normalize_peer_id_to_target,
)
from .converter import (
    pull_log_entry_request_to_interest_name,
    pull_log_entry_request_to_data_content,
    data_content_to_pull_log_entry_response
)

logger = logging.getLogger(__name__)


_ndn_client: Optional[NDNClient] = None
_ndn_queue: Optional[Queue] = None
_ndn_connected: Optional[asyncio.Event] = None


@dataclass
class InterestRequest:
    interest_name: str
    app_param: bytes
    lifetime: int
    must_be_fresh: bool
    future: Future


class TransparentForwardingHandler(grpc.GenericRpcHandler):
    """
    A GenericRpcHandler that catches *unknown* RPC methods and forwards them
    to a configured target server without decoding the protobuf payload.

    This is required because gRPC interceptors only run AFTER a method is found.
    In sidecar mode we intentionally do not implement/register most raft RPCs,
    so without this handler the server returns UNIMPLEMENTED immediately.

    Rules:
    - PullLogEntries: handled by the normal servicer (NDN conversion), so this
      handler returns None for that method.
    - Everything else: forwarded as raw bytes to `grpc.forward_target` (or
      metadata override).

    Traffic note (Kubernetes / JRaft):
    - ``context.peer()`` on inbound is whoever connected *to this* process (the
      Python sidecar port, e.g. 19090). Peers often call the *main* Raft gRPC
      port (e.g. 8181) directly, so you may only see same-pod / loopback IPs
      here. That does *not* by itself mean outbound forwarding failed; compare
      ``transparent_passthrough outbound_ok`` / ``outbound_fail`` lines.
    """
    def __init__(self, config_path: Optional[str] = None):
        self.config = get_config(config_path)
        raw_timeout = os.getenv("GRPC_FORWARD_TIMEOUT_SEC", "5")
        try:
            self._forward_timeout_sec = float(raw_timeout)
        except ValueError:
            self._forward_timeout_sec = 5.0

    def _coerce_forward_target_away_from_self_listen(self, target: str, method: str) -> str:
        """If target dials this process's gRPC port on loopback, use upstream JRaft instead (avoid self-loop)."""
        host, port_s = parse_grpc_target_address(target)
        if not host or not port_s:
            return target
        try:
            port = int(port_s)
        except ValueError:
            return target
        if port != self.config.get_grpc_server_port():
            return target
        hl = host.strip().lower()
        if hl not in ("localhost", "127.0.0.1", "::1"):
            return target
        upstream = self.config.get_grpc_upstream_raft_addr()
        logger.warning(
            "transparent_passthrough loop_guard: would dial sidecar listen (%s) for %s; using upstream_raft=%s",
            target,
            method,
            upstream,
        )
        return upstream

    def _get_target_from_metadata(self, context: grpc.aio.ServicerContext) -> Optional[str]:
        md = dict(context.invocation_metadata())
        return md.get('target') or md.get('x-forward-to') or md.get('x-target-server')

    def service(self, handler_call_details):
        method = handler_call_details.method or ""
        # Let the registered servicer handle our own PullLogEntries (proto3) endpoint.
        if method.endswith("/PullLogEntries"):
            return None

        # SOFA-JRaft grpc-impl uses `/<JavaClass>/_call` where JavaClass is request class name.
        # We only intercept PullLogEntryRequest and translate it to NDN; all other methods are forwarded as-is.
        is_jraft_call = method.endswith("/_call")
        is_jraft_pull = (
            is_jraft_call
            and (
                "RpcRequests$PullLogEntryRequest" in method
                or "RpcRequests.PullLogEntryRequest" in method
            )
        )

        # We only support unary-unary passthrough here (raft RPCs are unary).
        async def unary_unary_passthrough(request_bytes: bytes, context: grpc.aio.ServicerContext) -> bytes:
            try:
                inbound_peer = context.peer()
            except Exception:
                inbound_peer = "unknown"
            logger.info(
                "transparent_passthrough inbound: peer=%s method=%s request_bytes=%d",
                inbound_peer,
                method,
                len(request_bytes),
            )
            # Only convert PullLog to NDN when use_ndn is enabled; otherwise fall through and
            # forward it upstream like any other RPC (use_ndn=false => transparent passthrough).
            if is_jraft_pull and self.config.get_grpc_server_use_ndn():
                logger.info(
                    "transparent_passthrough jraft_branch: kind=pull_log_ndn (NDN path, no grpc outbound); method=%s",
                    method,
                )
                # Convert PullLogEntryRequest -> NDN Interest -> PullLogEntryResponse (protobuf bytes)
                try:
                    req = decode_pull_log_entry_request(request_bytes)
                except Exception as e:
                    context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                    context.set_details(f"Failed to decode PullLogEntryRequest: {e}")
                    return b""

                if _ndn_queue is None:
                    context.set_code(grpc.StatusCode.INTERNAL)
                    context.set_details("NDN queue not initialized")
                    return b""

                # Build NDN interest
                interest_name = pull_log_entry_request_to_interest_name(req)
                app_param = pull_log_entry_request_to_data_content(req)

                client_config = self.config.get_client_config()
                interest_lifetime = client_config.get('interest_lifetime', 4000)
                disable_cache = self.config.get_client_disable_cache()

                if _ndn_connected is not None and not _ndn_connected.is_set():
                    await _ndn_connected.wait()

                future = Future()
                _ndn_queue.put(InterestRequest(
                    interest_name=interest_name,
                    app_param=app_param,
                    lifetime=interest_lifetime,
                    must_be_fresh=disable_cache,
                    future=future
                ))

                timeout = (interest_lifetime / 1000) + 60
                try:
                    content = await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
                except asyncio.TimeoutError:
                    context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
                    context.set_details("Timeout waiting for NDN response")
                    return b""

                if not content:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details("No response from NDN")
                    return b""

                try:
                    return encode_pull_log_entry_response_from_ndn_content(content)
                except Exception as e:
                    context.set_code(grpc.StatusCode.INTERNAL)
                    context.set_details(f"Failed to encode PullLogEntryResponse: {e}")
                    return b""

            # RequestVote, AppendEntries, InstallSnapshot, etc. use this branch (not PullLogEntry).
            if is_jraft_call:
                logger.info(
                    "transparent_passthrough jraft_branch: kind=forward_rpc method=%s",
                    method,
                )

            target = self._get_target_from_metadata(context)
            if not target and is_jraft_call:
                # For SOFA-JRaft `_call` methods, try to derive target from request.peer_id.
                # Most raft RPC requests use peer_id as field #3; ReadIndexRequest uses #4.
                peer_id = extract_string_field(request_bytes, 3) or extract_string_field(request_bytes, 4)
                derived = normalize_peer_id_to_target(peer_id) if peer_id else None
                if derived:
                    # Rewrite the JRaft port to the peer sidecar port so that
                    # iptables OUTPUT rules (which only match APP_PORT / JRaft port)
                    # do NOT re-intercept sidecar-to-sidecar traffic.  This lets
                    # the entire stack run as uid=0 without redirect loops.
                    peer_sidecar_port = self.config.get_peer_sidecar_port()
                    host, _ = parse_grpc_target_address(derived)
                    if host:
                        target = f"{host}:{peer_sidecar_port}"
                    else:
                        target = derived
                    logger.info(
                        "Derived forward target from peer_id: %s -> %s (peer_sidecar_port=%d, method=%s)",
                        derived, target, peer_sidecar_port, method,
                    )

            if not target:
                target = self.config.get_grpc_forward_target()
            if not target:
                target = self.config.get_grpc_upstream_raft_addr()
                logger.info(
                    "transparent_passthrough local_fallback: method=%s forward_target=%s "
                    "(no peer_id/metadata/forward_target, fallback to grpc.server.upstream_raft / GRPC_UPSTREAM_RAFT)",
                    method,
                    target,
                )

            resolved_target = target
            target = rewrite_target_to_localhost_if_self(target)
            target = self._coerce_forward_target_away_from_self_listen(target, method)
            logger.info(
                "transparent_passthrough route: resolved_target=%s forward_target=%s local_identities=%s method=%s",
                resolved_target,
                target,
                collect_local_identity_hosts(),
                method,
            )

            try:
                channel = grpc.aio.insecure_channel(target)
                call = channel.unary_unary(
                    method,
                    request_serializer=lambda b: b,
                    response_deserializer=lambda b: b,
                )
                logger.info(
                    "transparent_passthrough outbound_begin: forward_target=%s method=%s timeout_sec=%.2f (awaiting response; "
                    "if this line exists but no outbound_ok/outbound_fail, remote is slow or hung)",
                    target,
                    method,
                    self._forward_timeout_sec,
                )
                resp = await asyncio.wait_for(
                    call(
                        request_bytes,
                        metadata=context.invocation_metadata(),
                        timeout=self._forward_timeout_sec,
                    ),
                    timeout=self._forward_timeout_sec + 0.5,
                )
                await channel.close()
                logger.info(
                    "transparent_passthrough outbound_ok: forward_target=%s method=%s response_bytes=%d",
                    target,
                    method,
                    len(resp),
                )
                return resp
            except asyncio.TimeoutError:
                try:
                    await channel.close()
                except Exception:
                    pass
                logger.warning(
                    "transparent_passthrough outbound_timeout: forward_target=%s method=%s timeout_sec=%.2f",
                    target,
                    method,
                    self._forward_timeout_sec,
                )
                context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
                context.set_details(f"Forward timeout after {self._forward_timeout_sec:.2f}s")
                return b""
            except asyncio.CancelledError:
                try:
                    await channel.close()
                except Exception:
                    pass
                try:
                    is_active = context.is_active()
                except Exception:
                    is_active = None
                try:
                    time_remaining = context.time_remaining()
                except Exception:
                    time_remaining = None
                logger.warning(
                    "transparent_passthrough outbound_cancelled: peer=%s forward_target=%s method=%s "
                    "context_active=%s time_remaining=%s",
                    inbound_peer,
                    target,
                    method,
                    is_active,
                    time_remaining,
                )
                raise
            except grpc.RpcError as e:
                try:
                    await channel.close()
                except Exception:
                    pass
                logger.warning(
                    "transparent_passthrough outbound_fail: forward_target=%s method=%s code=%s details=%s",
                    target,
                    method,
                    e.code(),
                    e.details() or "",
                )
                context.set_code(e.code())
                context.set_details(e.details() or "")
                return b""
            except Exception as e:
                try:
                    await channel.close()
                except Exception:
                    pass
                logger.error(
                    "transparent_passthrough outbound_error: forward_target=%s method=%s",
                    target,
                    method,
                    exc_info=True,
                )
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return b""
            finally:
                logger.info(
                    "transparent_passthrough outbound_finally: forward_target=%s method=%s",
                    target,
                    method,
                )

        return grpc.unary_unary_rpc_method_handler(
            unary_unary_passthrough,
            request_deserializer=lambda b: b,
            response_serializer=lambda b: b,
        )


class SimpleService(bidirectional_pb2_grpc.SimpleServiceServicer):
    def __init__(self, config_path: Optional[str] = None):
        self.config = get_config(config_path)
        self._forward_target = self.config.get_grpc_forward_target()
    
    def _get_target_address(self, request, context) -> Optional[str]:
        """
        Get target server address from request metadata or request fields.
        
        Priority:
        1. Check metadata for 'target' or 'x-forward-to' header
        2. Check if request has server_id or peer_id that might contain address
        3. Use configured forward_target as fallback
        
        Returns:
            Target server address (host:port) or None
        """
        metadata = dict(context.invocation_metadata())
        target = metadata.get('target') or metadata.get('x-forward-to') or metadata.get('x-target-server')
        if target:
            logger.debug(f"Found target address in metadata: {target}")
            return target
        
        if hasattr(request, 'server_id') and request.server_id:
            if ':' in request.server_id and not request.server_id.startswith('/'):
                logger.debug(f"Using server_id as target address: {request.server_id}")
                return request.server_id
        
        if self._forward_target:
            logger.debug(f"Using configured forward_target: {self._forward_target}")
            return self._forward_target
        
        return None
    
    def _forward_rpc(self, method_name: str, request, context):
        """
        Generic method to forward any RPC call to target server.
        
        Logic: All non-PullLogEntries RPC methods are forwarded directly (not converted to NDN).
        PullLogEntries is handled separately and always converted to NDN Interest.
        
        Args:
            method_name: Name of the RPC method to forward
            request: The request object
            context: gRPC servicer context
            
        Returns:
            Response from target server
        """
        target = self._get_target_address(request, context)
        if not target:
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            context.set_details(f"Method '{method_name}' not implemented and no target address found (check metadata or config)")
            raise NotImplementedError(f"Method '{method_name}' not implemented and no target address found")

        resolved_target = target
        target = rewrite_target_to_localhost_if_self(target)
        logger.info(
            "SimpleService forward route: resolved_target=%s forward_target=%s local_identities=%s method=%s",
            resolved_target,
            target,
            collect_local_identity_hosts(),
            method_name,
        )
        
        logger.info(f"Forwarding RPC method '{method_name}' to target server: {target}")
        try:
            channel = grpc.insecure_channel(target)
            stub = bidirectional_pb2_grpc.SimpleServiceStub(channel)
            method = getattr(stub, method_name)
            response = method(request)
            channel.close()
            logger.info(f"Successfully forwarded '{method_name}' and received response")
            return response
        except grpc.RpcError as e:
            if 'channel' in locals():
                channel.close()
            logger.error(f"gRPC error forwarding '{method_name}': {e.code()} - {e.details()}")
            context.set_code(e.code())
            context.set_details(e.details())
            raise
        except AttributeError as e:
            if 'channel' in locals():
                channel.close()
            logger.error(f"Method '{method_name}' not found on target server: {e}")
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            context.set_details(f"Method '{method_name}' not found on target server")
            raise
        except Exception as e:
            if 'channel' in locals():
                channel.close()
            logger.error(f"Error forwarding '{method_name}': {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error forwarding request: {str(e)}")
            raise
    
    def _is_pull_log_entry_request(self, request) -> bool:
        """Check if request is PullLogEntryRequest type."""
        return isinstance(request, bidirectional_pb2.PullLogEntryRequest)
    
    async def PullLogEntries(self, request: bidirectional_pb2.PullLogEntryRequest,
                            context: grpc.ServicerContext) -> bidirectional_pb2.PullLogEntryResponse:
        """
        Handle PullLogEntries RPC: convert to NDN Interest.
        
        This method handles PullLogEntryRequest type requests by converting them to NDN Interest.
        Other request types should be handled by their respective RPC methods, which will call _forward_rpc().
        """
        logger.info(
            "inbound_grpc PullLogEntries: group_id=%s server_id=%s peer_id=%s term=%s",
            request.group_id,
            request.server_id,
            request.peer_id,
            request.term,
        )
        
        use_ndn = self.config.get_grpc_server_use_ndn()
        
        if not use_ndn:
            # NDN disabled: forward PullLogEntries upstream like any other RPC (transparent passthrough).
            logger.info("NDN disabled: forwarding PullLogEntries to upstream like other RPCs")
            return await asyncio.to_thread(self._forward_rpc, 'PullLogEntries', request, context)
        
        if _ndn_client is None or _ndn_queue is None:
            logger.error("NDN client or queue not initialized")
            response = bidirectional_pb2.PullLogEntryResponse()
            response.success = False
            response.errorResponse.errorCode = 101
            response.errorResponse.errorMsg = "NDN client or queue not initialized"
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("NDN client or queue not initialized")
            return response
        
        interest_name = pull_log_entry_request_to_interest_name(request)
        request_content = pull_log_entry_request_to_data_content(request)
        logger.info(f"Converting PullLogEntries to Interest: {interest_name}, content length: {len(request_content)}")
        
        try:
            client_config = self.config.get_client_config()
            interest_lifetime = client_config.get('interest_lifetime', 4000)
            disable_cache = self.config.get_client_disable_cache()
            
            if _ndn_connected is not None and not _ndn_connected.is_set():
                logger.warning("NDN client not connected yet, waiting...")
                await _ndn_connected.wait()
            
            if _ndn_queue is None:
                logger.error("NDN queue not initialized")
                response = bidirectional_pb2.PullLogEntryResponse()
                response.success = False
                response.errorResponse.errorCode = 102
                response.errorResponse.errorMsg = "NDN queue not initialized"
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("NDN queue not initialized")
                return response
            
            future = Future()
            interest_request = InterestRequest(
                interest_name=interest_name,
                app_param=request_content,
                lifetime=interest_lifetime,
                must_be_fresh=disable_cache,
                future=future
            )
            
            _ndn_queue.put(interest_request)
            logger.info(f"Interest request added to queue: {interest_name}")
            
            timeout = (interest_lifetime / 1000) + 60
            content = await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
            
            if content:
                response = data_content_to_pull_log_entry_response(content)
                logger.info(f"Received Data from NDN, converted to PullLogEntryResponse: success={response.success}, term={response.term}")
                return response
            else:
                logger.warning("No Data received from NDN")
                response = bidirectional_pb2.PullLogEntryResponse()
                response.success = False
                response.errorResponse.errorCode = 103
                response.errorResponse.errorMsg = "No response from NDN"
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("No response from NDN")
                return response
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for NDN response")
            response = bidirectional_pb2.PullLogEntryResponse()
            response.success = False
            response.errorResponse.errorCode = 104
            response.errorResponse.errorMsg = "Timeout waiting for NDN response"
            context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
            context.set_details("Timeout waiting for NDN response")
            return response
        except Exception as e:
            logger.error(f"Error processing PullLogEntries request: {e}", exc_info=True)
            response = bidirectional_pb2.PullLogEntryResponse()
            response.success = False
            response.errorResponse.errorCode = 105
            response.errorResponse.errorMsg = str(e)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error: {str(e)}")
            return response


def create_server(port: Optional[int] = None, config_path: Optional[str] = None):
    global _ndn_queue
    
    config = get_config(config_path)
    if port is None:
        port = config.get_grpc_server_port()
    
    use_ndn = config.get_grpc_server_use_ndn()
    
    if use_ndn:
        if _ndn_queue is None:
            _ndn_queue = Queue()
            logger.info("NDN interest queue created")
    
    servicer = SimpleService(config_path=config_path)
    server = grpc.aio.server()
    bidirectional_pb2_grpc.add_SimpleServiceServicer_to_server(servicer, server)
    # Catch-all forwarding for methods not registered in our proto/service.
    server.add_generic_rpc_handlers((TransparentForwardingHandler(config_path=config_path),))
    
    listen_addr = f'[::]:{port}'
    server.add_insecure_port(listen_addr)
    
    logger.info(f"gRPC server starting on port {port}")
    logger.info(
        "Sidecar forward localhost rewrite: local identity hostnames = %s "
        "(used to detect when peer_id points at this pod; empty/wrong => no rewrite to localhost)",
        collect_local_identity_hosts(),
    )
    if use_ndn:
        logger.info("NDN enabled: PullLogEntryRequest will be converted to NDN Interest, other requests will be forwarded directly")
    else:
        logger.info("gRPC server running in default mode (NDN disabled)")
    return server


async def run_server_async(port: Optional[int] = None, config_path: Optional[str] = None):
    global _ndn_client, _ndn_queue, _ndn_connected
    
    server = create_server(port, config_path)
    
    config = get_config(config_path)
    use_ndn = config.get_grpc_server_use_ndn()
    
    if use_ndn:
        if _ndn_queue is None:
            logger.error("NDN queue not initialized")
            raise RuntimeError("NDN queue not initialized")
        
        if _ndn_connected is None:
            _ndn_connected = asyncio.Event()
        
        pib_path = config.get_ndn_pib_path()
        tpm_path = config.get_ndn_tpm_path()
        
        async def consume_interest_queue():
            await asyncio.sleep(1.0)
            _ndn_connected.set()
            logger.info("NDN client connected to NFD, starting interest queue consumer")
            
            while True:
                try:
                    request = await asyncio.to_thread(_ndn_queue.get)
                    logger.info(f"Processing interest from queue: {request.interest_name}")
                    
                    try:
                        content = await _ndn_client.express_interest_with_params(
                            request.interest_name,
                            request.app_param,
                            lifetime=request.lifetime,
                            must_be_fresh=request.must_be_fresh
                        )
                        request.future.set_result(content)
                    except Exception as e:
                        logger.error(f"Error processing interest: {e}", exc_info=True)
                        request.future.set_exception(e)
                except Exception as e:
                    logger.error(f"Error in interest queue consumer: {e}", exc_info=True)
        
        async def _after_start():
            asyncio.create_task(consume_interest_queue())
        
        def run_ndn_client():
            global _ndn_client
            _ndn_client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
            logger.info("NDN client initialized in NDN thread")
            _ndn_client.app.run_forever(after_start=_after_start())
        
        ndn_thread = threading.Thread(target=run_ndn_client, daemon=True)
        ndn_thread.start()
        
        try:
            await asyncio.wait_for(_ndn_connected.wait(), timeout=5.0)
            logger.info("NDN client started and connected in gRPC server event loop")
        except asyncio.TimeoutError:
            logger.warning("NDN client connection timeout, continuing anyway...")
            _ndn_connected.set()
    else:
        logger.info("NDN client disabled, skipping NDN initialization")
    
    await server.start()
    logger.info("gRPC server started, waiting for connections...")
    
    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Received stop signal, shutting down server...")
        if _ndn_client:
            _ndn_client.shutdown()
        await server.stop(grace=5)
        logger.info("Server closed")


def run_server(port: Optional[int] = None, config_path: Optional[str] = None):
    asyncio.run(run_server_async(port, config_path))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_server()

