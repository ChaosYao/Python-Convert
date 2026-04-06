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
    
    def pull_log_entries(self, request: bidirectional_pb2.PullLogEntryRequest) -> bidirectional_pb2.PullLogEntryResponse:
        """Call PullLogEntries RPC."""
        if not self.stub:
            self.connect()
        
        logger.info(f"Sending PullLogEntries request: group_id={request.group_id}, server_id={request.server_id}, peer_id={request.peer_id}")
        
        try:
            response = self.stub.PullLogEntries(request)
            logger.info(f"Received PullLogEntries response: success={response.success}, term={response.term}")
            return response
        except grpc.RpcError as e:
            logger.error(f"gRPC error: {e.code()} - {e.details()}")
            raise
        except Exception as e:
            logger.error(f"Error calling PullLogEntries: {e}", exc_info=True)
            raise

