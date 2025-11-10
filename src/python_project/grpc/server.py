# gRPC simple server implementation
import asyncio
import logging
import threading
import time
from concurrent import futures
from typing import Optional

import grpc

from ..config import get_config
from ..ndn.client import NDNClient
from . import bidirectional_pb2
from . import bidirectional_pb2_grpc
from .converter import data_content_to_grpc_data, grpc_data_to_data_content

logger = logging.getLogger(__name__)

_shared_ndn_client: Optional[NDNClient] = None
_shared_ndn_thread: Optional[threading.Thread] = None
_ndn_lock = threading.Lock()


def _get_shared_ndn_client(config_path: Optional[str] = None) -> Optional[NDNClient]:
    global _shared_ndn_client, _shared_ndn_thread
    
    with _ndn_lock:
        if _shared_ndn_client is None:
            config = get_config(config_path)
            pib_path = config.get_ndn_pib_path()
            tpm_path = config.get_ndn_tpm_path()
            _shared_ndn_client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
            
            if _shared_ndn_client and _shared_ndn_client.app:
                def run_ndn_app():
                    try:
                        _shared_ndn_client.app.run_forever()
                    except Exception as e:
                        logger.error(f"NDN client app error: {e}", exc_info=True)
                
                _shared_ndn_thread = threading.Thread(target=run_ndn_app, daemon=True)
                _shared_ndn_thread.start()
                logger.info("Shared NDN client app started in background thread")
                time.sleep(1)
        
        return _shared_ndn_client


class SimpleService(bidirectional_pb2_grpc.SimpleServiceServicer):
    def __init__(self, ndn_client: Optional[NDNClient] = None, enable_ndn: bool = False, config_path: Optional[str] = None):
        self.ndn_client = ndn_client
        self.enable_ndn = enable_ndn
        self.loop = None
        self.config = get_config(config_path)
        if enable_ndn and ndn_client is None:
            self.ndn_client = _get_shared_ndn_client(config_path)
    
    def Process(self, request: bidirectional_pb2.Data, 
                context: grpc.ServicerContext) -> bidirectional_pb2.Data:
        logger.info(f"Received gRPC request: value={request.value}, payload={request.payload}")
        
        if self.enable_ndn and self.ndn_client:
            client_config = self.config.get_client_config()
            interests = client_config.get('interests', [])
            
            if not interests:
                logger.warning("No interests configured, cannot send to NDN")
                return bidirectional_pb2.Data(value=0, payload="No interests configured")
            
            interest_name = interests[0]
            request_content = grpc_data_to_data_content(request)
            logger.info(f"Forwarding gRPC request to config prefix: {interest_name}, content length: {len(request_content)}")
            
            try:
                if self.loop is None:
                    self.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self.loop)
                
                interest_lifetime = client_config.get('interest_lifetime', 4000)
                content = self.loop.run_until_complete(
                    self.ndn_client.express_interest_with_params(interest_name, request_content, lifetime=interest_lifetime)
                )
                
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

