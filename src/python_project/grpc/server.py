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
from .converter import data_content_to_grpc_data, grpc_data_to_data_content

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


class SimpleService(bidirectional_pb2_grpc.SimpleServiceServicer):
    def __init__(self, config_path: Optional[str] = None):
        self.config = get_config(config_path)
    
    async def Process(self, request: bidirectional_pb2.Data, 
                      context: grpc.ServicerContext) -> bidirectional_pb2.Data:
        logger.info(f"Received gRPC request: value={request.value}, payload={request.payload}")
        
        # Check if NDN client should be used
        use_ndn = self.config.get_grpc_server_use_ndn()
        
        if not use_ndn:
            # Default gRPC server logic: echo back the request with modified value
            logger.info("Processing request with default gRPC logic (NDN disabled)")
            response = bidirectional_pb2.Data(
                value=request.value + 1,
                payload=f"Echo: {request.payload}"
            )
            logger.info(f"Returning gRPC response: value={response.value}, payload={response.payload}")
            return response
        
        # NDN client logic
        if _ndn_client is None or _ndn_queue is None:
            logger.error("NDN client or queue not initialized")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("NDN client or queue not initialized")
            return bidirectional_pb2.Data(value=0, payload="NDN client or queue not initialized")
        
        client_config = self.config.get_client_config()
        interests = client_config.get('interests', [])
        
        if not interests:
            logger.error("No interests configured, cannot send to NDN")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("No interests configured")
            return bidirectional_pb2.Data(value=0, payload="No interests configured")
        
        interest_name = interests[0]
        request_content = grpc_data_to_data_content(request)
        logger.info(f"Converting gRPC request to Interest: {interest_name}, content length: {len(request_content)}")
        
        try:
            interest_lifetime = client_config.get('interest_lifetime', 4000)
            disable_cache = self.config.get_client_disable_cache()
            
            if _ndn_connected is not None and not _ndn_connected.is_set():
                logger.warning("NDN client not connected yet, waiting...")
                await _ndn_connected.wait()
            
            if _ndn_queue is None:
                logger.error("NDN queue not initialized")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("NDN queue not initialized")
                return bidirectional_pb2.Data(value=0, payload="NDN queue not initialized")
            
            future = Future()
            request = InterestRequest(
                interest_name=interest_name,
                app_param=request_content,
                lifetime=interest_lifetime,
                must_be_fresh=disable_cache,
                future=future
            )
            
            _ndn_queue.put(request)
            logger.info(f"Interest request added to queue: {interest_name}")
            
            timeout = (interest_lifetime / 1000) + 60
            content = await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
            
            if content:
                response = data_content_to_grpc_data(content)
                logger.info(f"Received Data from NDN, converted to gRPC response: value={response.value}, payload={response.payload}")
                return response
            else:
                logger.warning("No Data received from NDN")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("No response from NDN")
                return bidirectional_pb2.Data(value=0, payload="No response from NDN")
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for NDN response")
            context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
            context.set_details("Timeout waiting for NDN response")
            return bidirectional_pb2.Data(value=0, payload="Timeout waiting for NDN response")
        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error: {str(e)}")
            return bidirectional_pb2.Data(value=0, payload=f"Error: {str(e)}")


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
    
    server = grpc.aio.server()
    bidirectional_pb2_grpc.add_SimpleServiceServicer_to_server(
        SimpleService(config_path=config_path), server
    )
    
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

