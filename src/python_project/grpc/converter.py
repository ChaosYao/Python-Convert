# Converter between gRPC and NDN
import base64
import json
import logging

from ..utils import extract_host_from_server_id

logger = logging.getLogger(__name__)


def pull_log_entry_request_to_interest_name(request) -> str:
    """
    Convert PullLogEntryRequest to NDN Interest name.
    Use server_id as target host; fallback to peer_id.
    """
    target_id = request.server_id or request.peer_id
    host = extract_host_from_server_id(target_id)
    return f"/raft/{host}/pull/{request.term}/{request.prev_log_index}"


def pull_log_entry_request_to_data_content(request) -> bytes:
    """
    Convert PullLogEntryRequest to bytes for Interest app_param.
    """
    data = {
        '_origin': 'grpc-sidecar',
        'group_id': request.group_id,
        'server_id': request.server_id,
        'peer_id': request.peer_id,
        'term': request.term,
        'prev_log_term': request.prev_log_term,
        'prev_log_index': request.prev_log_index
    }
    return json.dumps(data).encode()


def data_content_to_pull_log_entry_response(content: bytes):
    """
    Convert NDN Data content to PullLogEntryResponse.
    """
    from . import bidirectional_pb2
    
    try:
        data = json.loads(content.decode())
        
        response = bidirectional_pb2.PullLogEntryResponse()
        response.term = data.get('term', 0)
        response.success = data.get('success', False)
        response.last_log_index = data.get('last_log_index', 0)
        response.committed_index = data.get('committed_index', 0)
        
        # Parse entries with full EntryMeta structure
        if 'entries' in data and isinstance(data['entries'], list):
            for entry_data in data['entries']:
                entry = response.entries.add()
                entry.term = entry_data.get('term', 0)
                # EntryType: convert string to enum value
                entry_type_str = entry_data.get('type', 'ENTRY_TYPE_UNKNOWN')
                if isinstance(entry_type_str, int):
                    entry.type = entry_type_str
                else:
                    # Map string to enum
                    type_map = {
                        'ENTRY_TYPE_UNKNOWN': bidirectional_pb2.ENTRY_TYPE_UNKNOWN,
                        'ENTRY_TYPE_NO_OP': bidirectional_pb2.ENTRY_TYPE_NO_OP,
                        'ENTRY_TYPE_DATA': bidirectional_pb2.ENTRY_TYPE_DATA,
                        'ENTRY_TYPE_CONFIGURATION': bidirectional_pb2.ENTRY_TYPE_CONFIGURATION,
                    }
                    entry.type = type_map.get(entry_type_str.upper(), bidirectional_pb2.ENTRY_TYPE_UNKNOWN)
                
                # Peers
                if 'peers' in entry_data:
                    entry.peers.extend(entry_data['peers'])
                
                # Data length
                if 'data_len' in entry_data:
                    entry.data_len = entry_data['data_len']
                
                # Old peers
                if 'old_peers' in entry_data:
                    entry.old_peers.extend(entry_data['old_peers'])
                
                # Checksum
                if 'checksum' in entry_data:
                    entry.checksum = entry_data['checksum']
                
                # Learners
                if 'learners' in entry_data:
                    entry.learners.extend(entry_data['learners'])
                
                # Old learners
                if 'old_learners' in entry_data:
                    entry.old_learners.extend(entry_data['old_learners'])
        
        # Parse data field: decode base64 if it's a string, otherwise use bytes directly
        if 'data' in data:
            if isinstance(data['data'], str):
                try:
                    # Try base64 decode first (for binary data)
                    response.data = base64.b64decode(data['data'])
                except Exception:
                    # If base64 decode fails, treat as UTF-8 text
                    response.data = data['data'].encode('utf-8')
            elif isinstance(data['data'], bytes):
                response.data = data['data']
        
        # Parse error response (using errorCode and errorMsg)
        if 'errorResponse' in data:
            error_data = data['errorResponse']
            response.errorResponse.errorCode = error_data.get('errorCode', 0)
            response.errorResponse.errorMsg = error_data.get('errorMsg', '')
        
        return response
    except Exception as e:
        logger.error(f"Failed to parse Data content to PullLogEntryResponse: {e}", exc_info=True)
        # Return error response
        response = bidirectional_pb2.PullLogEntryResponse()
        response.success = False
        response.errorResponse.errorCode = 1  # PARSE_ERROR
        response.errorResponse.errorMsg = str(e)
        return response



