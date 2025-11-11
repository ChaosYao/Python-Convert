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


_ndn_client: Optional[NDNClient] = None
_ndn_lock: Optional[asyncio.Lock] = None


class SimpleService(bidirectional_pb2_grpc.SimpleServiceServicer):
    def __init__(self, config_path: Optional[str] = None):
        self.config = get_config(config_path)
    
    async def Process(self, request: bidirectional_pb2.Data, 
                      context: grpc.ServicerContext) -> bidirectional_pb2.Data:
        logger.info(f"Received gRPC request: value={request.value}, payload={request.payload}")
        
        if _ndn_client is None:
            logger.error("NDN client not initialized")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("NDN client not initialized")
            return bidirectional_pb2.Data(value=0, payload="NDN client not initialized")
        
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
            
            if _ndn_lock is not None:
                async with _ndn_lock:
                    try:
                        content = await _ndn_client.express_interest_with_params(
                            interest_name,
                            request_content,
                            lifetime=interest_lifetime,
                            must_be_fresh=disable_cache
                        )
                    except Exception as e:
                        if "cannot send packet before connected" in str(e):
                            logger.error("NDN client not connected yet, waiting...")
                            await asyncio.sleep(1.0)
                            content = await _ndn_client.express_interest_with_params(
                                interest_name,
                                request_content,
                                lifetime=interest_lifetime,
                                must_be_fresh=disable_cache
                            )
                        else:
                            raise
            else:
                try:
                    content = await _ndn_client.express_interest_with_params(
                        interest_name,
                        request_content,
                        lifetime=interest_lifetime,
                        must_be_fresh=disable_cache
                    )
                except Exception as e:
                    if "cannot send packet before connected" in str(e):
                        logger.error("NDN client not connected yet, waiting...")
                        await asyncio.sleep(1.0)
                        content = await _ndn_client.express_interest_with_params(
                            interest_name,
                            request_content,
                            lifetime=interest_lifetime,
                            must_be_fresh=disable_cache
                        )
                    else:
                        raise
            
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


def create_server(port: Optional[int] = None, config_path: Optional[str] = None, 
                  enable_ndn: bool = False):
    global _ndn_client
    
    if port is None:
        config = get_config(config_path)
        port = config.get_grpc_server_port()
    
    if enable_ndn and _ndn_client is None:
        config = get_config(config_path)
        pib_path = config.get_ndn_pib_path()
        tpm_path = config.get_ndn_tpm_path()
        _ndn_client = NDNClient(pib_path=pib_path, tpm_path=tpm_path)
        logger.info("NDN client initialized for gRPC server")
    
    server = grpc.aio.server()
    bidirectional_pb2_grpc.add_SimpleServiceServicer_to_server(
        SimpleService(config_path=config_path), server
    )
    
    listen_addr = f'[::]:{port}'
    server.add_insecure_port(listen_addr)
    
    logger.info(f"gRPC server starting on port {port}")
    if enable_ndn:
        logger.info("All gRPC requests will be routed through NDN")
    return server


async def run_server_async(port: Optional[int] = None, config_path: Optional[str] = None, enable_ndn: bool = False):
    global _ndn_client, _ndn_lock
    
    server = create_server(port, config_path, enable_ndn=enable_ndn)
    
    if enable_ndn and _ndn_client:
        if _ndn_lock is None:
            _ndn_lock = asyncio.Lock()
            logger.info("NDN lock initialized in event loop")
        
        async def run_ndn_client():
            await _ndn_client.app.run_forever()
        
        ndn_task = asyncio.create_task(run_ndn_client())
        await asyncio.sleep(2.0)
        logger.info("NDN client started in gRPC server event loop")
    
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


def run_server(port: Optional[int] = None, config_path: Optional[str] = None, enable_ndn: bool = False):
    asyncio.run(run_server_async(port, config_path, enable_ndn))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_server()

