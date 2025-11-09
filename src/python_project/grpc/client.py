# gRPC simple client implementation
import logging
from typing import Optional

import grpc

from ..config import get_config
from . import bidirectional_pb2
from . import bidirectional_pb2_grpc

logger = logging.getLogger(__name__)


class SimpleClient:
    def __init__(self, server_address: Optional[str] = None, config_path: Optional[str] = None):
        if server_address is None:
            config = get_config(config_path)
            server_address = config.get_grpc_client_host()
        self.server_address = server_address
        self.channel = None
        self.stub = None
    
    def connect(self):
        self.channel = grpc.insecure_channel(self.server_address)
        self.stub = bidirectional_pb2_grpc.SimpleServiceStub(self.channel)
        logger.info(f"Connected to server: {self.server_address}")
    
    def disconnect(self):
        if self.channel:
            self.channel.close()
            logger.info("Disconnected")
    
    def process_data(self, value: int, payload: str) -> bidirectional_pb2.Data:
        if not self.stub:
            self.connect()
        
        request = bidirectional_pb2.Data(
            value=value,
            payload=payload
        )
        
        logger.info(f"Sending data: value={value}, payload={payload}")
        
        try:
            response = self.stub.Process(request)
            logger.info(f"Received response: value={response.value}, payload={response.payload}")
            return response
        except grpc.RpcError as e:
            logger.error(f"gRPC error: {e.code()} - {e.details()}")
            raise
        except Exception as e:
            logger.error(f"Error sending data: {e}", exc_info=True)
            raise


def run_client(server_address: Optional[str] = None,
               data_list: Optional[list[tuple[int, str]]] = None,
               config_path: Optional[str] = None):
    config = get_config(config_path)
    
    if server_address is None:
        server_address = config.get_grpc_client_host()
    
    if data_list is None:
        data_list = config.get_grpc_test_data()
    
    client = SimpleClient(server_address, config_path)
    try:
        client.connect()
        for value, payload in data_list:
            response = client.process_data(value, payload)
            logger.info(f"Result: value={response.value}, payload={response.payload}")
    finally:
        client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_client()

