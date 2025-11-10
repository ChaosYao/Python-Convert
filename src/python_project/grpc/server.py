# gRPC simple server implementation
import asyncio
import logging
import threading
import time
import uuid
from concurrent import futures
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Optional, Callable, Any
from queue import Queue

import grpc

from ..config import get_config
from ..ndn.client import NDNClient
from . import bidirectional_pb2
from . import bidirectional_pb2_grpc
from .converter import data_content_to_grpc_data, grpc_data_to_data_content

logger = logging.getLogger(__name__)


@dataclass
class InterestRequest:
    request_id: str
    interest_name: str
    app_param: bytes
    lifetime: int
    future: Future
    must_be_fresh: bool = False


_shared_ndn_client: Optional[NDNClient] = None
_shared_ndn_thread: Optional[threading.Thread] = None
_ndn_consumer_thread: Optional[threading.Thread] = None
_ndn_lock = threading.Lock()
_ndn_loop: Optional[asyncio.AbstractEventLoop] = None
_ndn_queue: Optional[Queue] = None
_ndn_initialized = False


def _init_ndn_client(config_path: Optional[str] = None) -> bool:
    global _shared_ndn_client, _shared_ndn_thread, _ndn_consumer_thread, _ndn_loop, _ndn_queue, _ndn_initialized
    
    with _ndn_lock:
        if _ndn_initialized:
            return _shared_ndn_client is not None
        
        _ndn_queue = Queue()
        config = get_config(config_path)
        pib_path = config.get_ndn_pib_path()
        tpm_path = config.get_ndn_tpm_path()
        
        def create_and_run_ndn_client():
            global _shared_ndn_client, _ndn_loop
            try:
                _ndn_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_ndn_loop)
                _shared_ndn_client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
                if _shared_ndn_client and _shared_ndn_client.app:
                    logger.info("NDN client created in background thread")
                    _shared_ndn_client.app.run_forever()
                else:
                    logger.error("Failed to create NDN client")
            except Exception as e:
                logger.error(f"NDN client app error: {e}", exc_info=True)
        
        def consume_interest_queue():
            global _ndn_loop, _shared_ndn_client
            logger.info("NDN interest queue consumer started")
            
            while True:
                try:
                    request: InterestRequest = _ndn_queue.get()
                    if request is None:
                        logger.info("NDN queue consumer received shutdown signal")
                        break
                    
                    logger.info(f"Processing interest request: {request.request_id}, name: {request.interest_name}")
                    
                    if _ndn_loop is None or _shared_ndn_client is None:
                        logger.error("NDN client or loop not available")
                        request.future.set_result(None)
                        _ndn_queue.task_done()
                        continue
                    
                    coro = _shared_ndn_client.express_interest_with_params(
                        request.interest_name,
                        request.app_param,
                        lifetime=request.lifetime,
                        must_be_fresh=request.must_be_fresh
                    )
                    
                    future = asyncio.run_coroutine_threadsafe(coro, _ndn_loop)
                    try:
                        timeout = (request.lifetime / 1000) + 2
                        content = future.result(timeout=timeout)
                        request.future.set_result(content)
                        logger.info(f"Interest request {request.request_id} completed")
                    except TimeoutError:
                        logger.error(f"Timeout waiting for NDN response: {request.request_id}")
                        request.future.set_result(None)
                    except Exception as e:
                        logger.error(f"Error processing interest {request.request_id}: {e}", exc_info=True)
                        request.future.set_result(None)
                    
                    _ndn_queue.task_done()
                except Exception as e:
                    logger.error(f"Error in queue consumer: {e}", exc_info=True)
        
        _shared_ndn_thread = threading.Thread(target=create_and_run_ndn_client, daemon=True)
        _shared_ndn_thread.start()
        logger.info("NDN client thread started, waiting for initialization...")
        
        max_wait = 10
        waited = 0
        while _shared_ndn_client is None and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
        
        if _shared_ndn_client is None:
            logger.error("Failed to create NDN client in background thread")
            _ndn_initialized = True
            return False
        
        max_wait_loop = 5
        waited_loop = 0
        while (_ndn_loop is None or not _ndn_loop.is_running()) and waited_loop < max_wait_loop:
            time.sleep(0.1)
            waited_loop += 0.1
        
        if _ndn_loop is None or not _ndn_loop.is_running():
            logger.warning("NDN loop may not be running yet, but continuing...")
        
        _ndn_consumer_thread = threading.Thread(target=consume_interest_queue, daemon=True)
        _ndn_consumer_thread.start()
        logger.info("NDN interest queue consumer thread started")
        
        _ndn_initialized = True
        return True


def _get_shared_ndn_client(config_path: Optional[str] = None) -> Optional[NDNClient]:
    if not _ndn_initialized:
        _init_ndn_client(config_path)
    return _shared_ndn_client


def _submit_interest_request(interest_name: str, app_param: bytes, lifetime: int, must_be_fresh: bool = False) -> Optional[bytes]:
    global _ndn_queue
    
    if _ndn_queue is None:
        logger.error("NDN queue not initialized")
        return None
    
    request_id = str(uuid.uuid4())
    future = Future()
    
    request = InterestRequest(
        request_id=request_id,
        interest_name=interest_name,
        app_param=app_param,
        lifetime=lifetime,
        future=future,
        must_be_fresh=must_be_fresh
    )
    
    _ndn_queue.put(request)
    logger.info(f"Interest request {request_id} submitted to queue")
    
    try:
        timeout = (lifetime / 1000) + 2
        content = future.result(timeout=timeout)
        return content
    except TimeoutError:
        logger.error(f"Timeout waiting for interest request {request_id}")
        return None
    except Exception as e:
        logger.error(f"Error waiting for interest request {request_id}: {e}", exc_info=True)
        return None


class SimpleService(bidirectional_pb2_grpc.SimpleServiceServicer):
    def __init__(self, ndn_client: Optional[NDNClient] = None, enable_ndn: bool = False, config_path: Optional[str] = None):
        self.enable_ndn = enable_ndn
        self.config = get_config(config_path)
    
    def Process(self, request: bidirectional_pb2.Data, 
                context: grpc.ServicerContext) -> bidirectional_pb2.Data:
        logger.info(f"Received gRPC request: value={request.value}, payload={request.payload}")
        
        if self.enable_ndn:
            client_config = self.config.get_client_config()
            interests = client_config.get('interests', [])
            
            if not interests:
                logger.warning("No interests configured, cannot send to NDN")
                return bidirectional_pb2.Data(value=0, payload="No interests configured")
            
            interest_name = interests[0]
            request_content = grpc_data_to_data_content(request)
            logger.info(f"Converting gRPC request to Interest: {interest_name}, content length: {len(request_content)}")
            
            try:
                interest_lifetime = client_config.get('interest_lifetime', 4000)
                disable_cache = self.config.get_client_disable_cache()
                content = _submit_interest_request(interest_name, request_content, interest_lifetime, must_be_fresh=disable_cache)
                
                if content:
                    response = data_content_to_grpc_data(content)
                    logger.info(f"Received Data from NDN, converted to gRPC response: value={response.value}, payload={response.payload}")
                    return response
                else:
                    logger.warning("No Data received from NDN")
                    return bidirectional_pb2.Data(value=0, payload="No response from NDN")
            except Exception as e:
                logger.error(f"Error processing request: {e}", exc_info=True)
                return bidirectional_pb2.Data(value=0, payload=f"Error: {str(e)}")
        else:
            response = bidirectional_pb2.Data(
                value=request.value * 2,
                payload=f"Processed: {request.payload}"
            )
            logger.info(f"Sending response: value={response.value}, payload={response.payload}")
            return response


def create_server(port: Optional[int] = None, config_path: Optional[str] = None, 
                  ndn_client: Optional[NDNClient] = None, enable_ndn: bool = False) -> grpc.Server:
    if port is None:
        config = get_config(config_path)
        port = config.get_grpc_server_port()
    
    if enable_ndn:
        logger.info("Initializing NDN client for gRPC-to-NDN conversion...")
        if not _init_ndn_client(config_path):
            logger.warning("Failed to initialize NDN client, continuing without NDN support")
            enable_ndn = False
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bidirectional_pb2_grpc.add_SimpleServiceServicer_to_server(
        SimpleService(ndn_client=ndn_client, enable_ndn=enable_ndn, config_path=config_path), server
    )
    
    listen_addr = f'[::]:{port}'
    server.add_insecure_port(listen_addr)
    
    logger.info(f"gRPC server starting on port {port}")
    if enable_ndn:
        logger.info("gRPC-to-NDN conversion enabled")
    return server


def run_server(port: Optional[int] = None, config_path: Optional[str] = None, enable_ndn: bool = False):
    server = create_server(port, config_path, enable_ndn=enable_ndn)
    server.start()
    logger.info("gRPC server started, waiting for connections...")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Received stop signal, shutting down server...")
        server.stop(grace=5)
        logger.info("Server closed")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_server()

