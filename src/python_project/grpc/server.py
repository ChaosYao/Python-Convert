# gRPC simple server implementation
import logging
from concurrent import futures
from typing import Optional

import grpc

from ..config import get_config
from . import bidirectional_pb2
from . import bidirectional_pb2_grpc

logger = logging.getLogger(__name__)


class SimpleService(bidirectional_pb2_grpc.SimpleServiceServicer):
    def Process(self, request: bidirectional_pb2.Data, 
                context: grpc.ServicerContext) -> bidirectional_pb2.Data:
        logger.info(f"Received data: value={request.value}, payload={request.payload}")
        
        response = bidirectional_pb2.Data(
            value=request.value * 2,
            payload=f"Processed: {request.payload}"
        )
        
        logger.info(f"Sending response: value={response.value}, payload={response.payload}")
        return response


def create_server(port: Optional[int] = None, config_path: Optional[str] = None) -> grpc.Server:
    if port is None:
        config = get_config(config_path)
        port = config.get_grpc_server_port()
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bidirectional_pb2_grpc.add_SimpleServiceServicer_to_server(
        SimpleService(), server
    )
    
    listen_addr = f'[::]:{port}'
    server.add_insecure_port(listen_addr)
    
    logger.info(f"gRPC server starting on port {port}")
    return server


def run_server(port: Optional[int] = None, config_path: Optional[str] = None):
    server = create_server(port, config_path)
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

