# gRPC simple server implementation
import asyncio
import logging
import threading
from queue import Queue
from dataclasses import dataclass
from concurrent.futures import Future
from typing import Optional

import grpc

from ..config import get_config
from ..ndn.client import NDNClient
from . import bidirectional_pb2
from . import bidirectional_pb2_grpc
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


class RequestRouterInterceptor(grpc.aio.ServerInterceptor):
    """
    gRPC interceptor to route requests based on request type.
    - PullLogEntryRequest -> convert to NDN Interest
    - Other requests -> forward to target server
    """
    def __init__(self, servicer):
        self.servicer = servicer
    
    async def intercept_service(self, continuation, handler_call_details):
        """Intercept all RPC calls and route based on request type."""
        # Get the original handler
        handler = await continuation(handler_call_details)
        
        if handler is None:
            return None
        
        # Get method name from handler_call_details
        method_name = handler_call_details.method.split('/')[-1] if handler_call_details.method else None
        
        # Create a wrapper handler that checks request type
        async def wrapper_handler(request, context):
            # Check if request is PullLogEntryRequest
            if isinstance(request, bidirectional_pb2.PullLogEntryRequest):
                # Convert to NDN Interest
                logger.info(f"Routing {method_name} to NDN conversion (PullLogEntryRequest detected)")
                return await self.servicer.PullLogEntries(request, context)
            else:
                # Forward to target server
                logger.info(f"Routing {method_name} to forward (non-PullLogEntryRequest: {type(request).__name__})")
                return self.servicer._forward_rpc(method_name, request, context)
        
        # Return the wrapper handler directly
        # The handler should be callable with (request, context)
        return wrapper_handler


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
        # Try to get from metadata first
        metadata = dict(context.invocation_metadata())
        target = metadata.get('target') or metadata.get('x-forward-to') or metadata.get('x-target-server')
        if target:
            logger.debug(f"Found target address in metadata: {target}")
            return target
        
        # Try to extract from request fields (e.g., server_id might be in format "host:port")
        if hasattr(request, 'server_id') and request.server_id:
            # Check if server_id looks like an address (contains ':')
            if ':' in request.server_id and not request.server_id.startswith('/'):
                logger.debug(f"Using server_id as target address: {request.server_id}")
                return request.server_id
        
        # Fallback to configured forward_target
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
        # All non-PullLogEntries methods are forwarded directly
        # Get target address from metadata, request fields, or configuration
        target = self._get_target_address(request, context)
        if not target:
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            context.set_details(f"Method '{method_name}' not implemented and no target address found (check metadata or config)")
            raise NotImplementedError(f"Method '{method_name}' not implemented and no target address found")
        
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
        logger.info(f"Received PullLogEntries request: group_id={request.group_id}, server_id={request.server_id}, peer_id={request.peer_id}, term={request.term}")
        
        # PullLogEntryRequest is always converted to NDN Interest (not forwarded)
        
        # Check if NDN client should be used
        use_ndn = self.config.get_grpc_server_use_ndn()
        
        if not use_ndn:
            logger.warning("NDN is disabled, but request reached here. This should not happen in sidecar mode.")
            response = bidirectional_pb2.PullLogEntryResponse()
            response.success = False
            response.errorResponse.errorCode = 100  # NDN_DISABLED
            response.errorResponse.errorMsg = "NDN processing is disabled"
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            context.set_details("NDN processing is disabled")
            return response
        
        # Convert to NDN Interest
        if _ndn_client is None or _ndn_queue is None:
            logger.error("NDN client or queue not initialized")
            response = bidirectional_pb2.PullLogEntryResponse()
            response.success = False
            response.errorResponse.errorCode = 101  # NDN_NOT_INITIALIZED
            response.errorResponse.errorMsg = "NDN client or queue not initialized"
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("NDN client or queue not initialized")
            return response
        
        # Generate Interest name from request
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
                response.errorResponse.errorCode = 102  # NDN_QUEUE_NOT_INITIALIZED
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
                response.errorResponse.errorCode = 103  # NO_RESPONSE
                response.errorResponse.errorMsg = "No response from NDN"
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("No response from NDN")
                return response
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for NDN response")
            response = bidirectional_pb2.PullLogEntryResponse()
            response.success = False
            response.errorResponse.errorCode = 104  # TIMEOUT
            response.errorResponse.errorMsg = "Timeout waiting for NDN response"
            context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
            context.set_details("Timeout waiting for NDN response")
            return response
        except Exception as e:
            logger.error(f"Error processing PullLogEntries request: {e}", exc_info=True)
            response = bidirectional_pb2.PullLogEntryResponse()
            response.success = False
            response.errorResponse.errorCode = 105  # INTERNAL_ERROR
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
    
    # Create servicer instance
    servicer = SimpleService(config_path=config_path)
    
    # Create server with interceptor to route requests based on type
    interceptor = RequestRouterInterceptor(servicer)
    server = grpc.aio.server(interceptors=[interceptor])
    
    # Register servicer
    bidirectional_pb2_grpc.add_SimpleServiceServicer_to_server(servicer, server)
    
    listen_addr = f'[::]:{port}'
    server.add_insecure_port(listen_addr)
    
    logger.info(f"gRPC server starting on port {port}")
    if use_ndn:
        logger.info("All gRPC requests will be routed through NDN")
    else:
        logger.info("gRPC server running in default mode (NDN disabled)")
    return server


async def run_server_async(port: Optional[int] = None, config_path: Optional[str] = None):
    global _ndn_client, _ndn_queue, _ndn_connected
    
    server = create_server(port, config_path)
    
    config = get_config(config_path)
    use_ndn = config.get_grpc_server_use_ndn()
    
    # Only initialize NDN client if use_ndn is True
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

