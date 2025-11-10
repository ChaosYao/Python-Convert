# Simple converter between gRPC and NDN
import json
import logging

logger = logging.getLogger(__name__)


def grpc_request_to_interest_name(grpc_data) -> str:
    # Not implemented - all requests are forwarded to config prefix
    return f"/grpc/process/{grpc_data.value}/{grpc_data.payload}"


def interest_name_to_grpc_request(name: str):
    # Not implemented - all requests are extracted from Interest app_param
    from . import bidirectional_pb2
    
    parts = name.split('/')
    if len(parts) >= 4 and parts[1] == 'grpc' and parts[2] == 'process':
        try:
            value = int(parts[3])
            payload = '/'.join(parts[4:]) if len(parts) > 4 else f"from_ndn_{value}"
            return bidirectional_pb2.Data(value=value, payload=payload)
        except ValueError:
            pass
    
    return bidirectional_pb2.Data(value=0, payload=name)


def data_content_to_grpc_data(content: bytes):
    from . import bidirectional_pb2
    
    try:
        data = json.loads(content.decode())
        return bidirectional_pb2.Data(
            value=data.get('value', 0),
            payload=data.get('payload', '')
        )
    except:
        try:
            value = int(content.decode())
            return bidirectional_pb2.Data(value=value, payload=content.decode())
        except:
            return bidirectional_pb2.Data(value=0, payload=content.decode())


def grpc_data_to_data_content(grpc_data) -> bytes:
    data = {
        'value': grpc_data.value,
        'payload': grpc_data.payload
    }
    return json.dumps(data).encode()

