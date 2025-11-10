# gRPC simple server implementation
import asyncio
import logging
from typing import Optional

import grpc

from ..config import get_config
from ..ndn.client import NDNClient
from . import bidirectional_pb2
from . import bidirectional_pb2_grpc
from .converter import data_content_to_grpc_data, grpc_data_to_data_content

logger = logging.getLogger(__name__)


_shared_ndn_client: Optional[NDNClient] = None


def set_shared_ndn_client(ndn_client: NDNClient):
    global _shared_ndn_client
    _shared_ndn_client = ndn_client
    logger.info("Shared NDN client set for gRPC server")


class SimpleService(bidirectional_pb2_grpc.SimpleServiceServicer):
    def __init__(self, ndn_client: Optional[NDNClient] = None, enable_ndn: bool = False, config_path: Optional[str] = None):
        self.enable_ndn = enable_ndn
        self.config = get_config(config_path)
    
    async def Process(self, request: bidirectional_pb2.Data, 
                      context: grpc.ServicerContext) -> bidirectional_pb2.Data:
        logger.info(f"Received gRPC request: value={request.value}, payload={request.payload}")
        
        if self.enable_ndn:
            if _shared_ndn_client is None:
                logger.warning("NDN client not set")
                return bidirectional_pb2.Data(value=0, payload="NDN client not set")
            
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
                content = await _shared_ndn_client.express_interest_with_params(
                    interest_name,
                    request_content,
                    lifetime=interest_lifetime,
                    must_be_fresh=disable_cache
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
                  ndn_client: Optional[NDNClient] = None, enable_ndn: bool = False):
    if port is None:
        config = get_config(config_path)
        port = config.get_grpc_server_port()
    
    if enable_ndn:
        if _shared_ndn_client is None:
            logger.warning("NDN client not set, continuing without NDN support")
            enable_ndn = False
    
    server = grpc.aio.server()
    bidirectional_pb2_grpc.add_SimpleServiceServicer_to_server(
        SimpleService(ndn_client=ndn_client, enable_ndn=enable_ndn, config_path=config_path), server
    )
    
    listen_addr = f'[::]:{port}'
    server.add_insecure_port(listen_addr)
    
    logger.info(f"gRPC server starting on port {port}")
    if enable_ndn:
        logger.info("gRPC-to-NDN conversion enabled")
    return server


async def run_server_async(port: Optional[int] = None, config_path: Optional[str] = None, enable_ndn: bool = False):
    server = create_server(port, config_path, enable_ndn=enable_ndn)
    await server.start()
    logger.info("gRPC server started, waiting for connections...")
    
    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Received stop signal, shutting down server...")
        await server.stop(grace=5)
        logger.info("Server closed")


def run_server(port: Optional[int] = None, config_path: Optional[str] = None, enable_ndn: bool = False):
    asyncio.run(run_server_async(port, config_path, enable_ndn))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_server()

