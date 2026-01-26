"""
Minimal protobuf (wire) codec for SOFA-JRaft PullLogEntryRequest/Response.

Why:
- In SOFA-JRaft grpc-impl, method path is `/<JavaClass>/_call` and payload is a protobuf Message.
- Cursor sandbox may not have google/protobuf installed; also we only need a tiny subset.
- This module implements just enough protobuf wire encoding/decoding for:
  - RpcRequests.PullLogEntryRequest  (fields 1..6)
  - RpcRequests.PullLogEntryResponse (fields 1,2,3,4,5,6,99)
  - RaftOutter.EntryMeta             (fields 1..8)
  - RpcRequests.ErrorResponse        (fields 1,2)

All fields follow the definitions in sofa-jraft `jraft-core/src/main/resources/{rpc,raft,enum}.proto`.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


# --- Protobuf wire helpers ----------------------------------------------------

WIRE_VARINT = 0
WIRE_LEN = 2


def _encode_varint(value: int) -> bytes:
    # protobuf varint uses unsigned; int64 values we have are non-negative
    if value < 0:
        # fallback to 64-bit two's complement
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _decode_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    shift = 0
    result = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, pos
        shift += 7
        if shift > 70:
            raise ValueError("varint too long")


def _encode_key(field_no: int, wire_type: int) -> bytes:
    return _encode_varint((field_no << 3) | wire_type)


def _encode_len_delimited(data: bytes) -> bytes:
    return _encode_varint(len(data)) + data


def _skip_field(buf: bytes, pos: int, wire_type: int) -> int:
    if wire_type == WIRE_VARINT:
        _, pos = _decode_varint(buf, pos)
        return pos
    if wire_type == WIRE_LEN:
        ln, pos = _decode_varint(buf, pos)
        return pos + ln
    raise ValueError(f"unsupported wire_type={wire_type}")


def extract_string_field(buf: bytes, field_no: int) -> Optional[str]:
    """
    Extract the first occurrence of a string field from a proto2/proto3 message bytes.
    This is used for "transparent forwarding" routing decisions without a full protobuf runtime.
    """
    pos = 0
    while pos < len(buf):
        key, pos = _decode_varint(buf, pos)
        fno = key >> 3
        wire_type = key & 0x7
        if fno == field_no and wire_type == WIRE_LEN:
            ln, pos = _decode_varint(buf, pos)
            val = buf[pos:pos + ln].decode("utf-8", errors="replace")
            pos += ln
            return val
        pos = _skip_field(buf, pos, wire_type)
    return None


def normalize_peer_id_to_target(peer_id: str) -> Optional[str]:
    """
    Convert sofa-jraft peer_id/server_id style strings into a dialable host:port.
    Examples:
      "rhea_example-1/raft-1.raft.ns.svc.cluster.local:8181" -> "raft-1.raft.ns.svc.cluster.local:8181"
      "raft-1.raft.ns.svc.cluster.local:8181" -> same
    """
    if not peer_id:
        return None
    s = peer_id.strip()
    # remove wrapping <> if present in logs
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    # take last path segment
    s = s.rsplit("/", 1)[-1]
    if not s:
        return None
    # must contain port to be dialable
    if ":" not in s:
        return None
    return s


# --- Request/Response types ---------------------------------------------------


@dataclass
class PullLogEntryRequestLite:
    group_id: str = ""
    server_id: str = ""
    peer_id: str = ""
    term: int = 0
    prev_log_term: int = 0
    prev_log_index: int = 0


def decode_pull_log_entry_request(buf: bytes) -> PullLogEntryRequestLite:
    """
    Decode sofa-jraft RpcRequests.PullLogEntryRequest (proto2) from bytes.
    Fields:
      1 group_id (string)
      2 server_id (string)
      3 peer_id (string)
      4 term (int64)
      5 prev_log_term (int64)
      6 prev_log_index (int64)
    """
    req = PullLogEntryRequestLite()
    pos = 0
    while pos < len(buf):
        key, pos = _decode_varint(buf, pos)
        field_no = key >> 3
        wire_type = key & 0x7
        if field_no in (1, 2, 3) and wire_type == WIRE_LEN:
            ln, pos = _decode_varint(buf, pos)
            val = buf[pos:pos + ln].decode("utf-8", errors="replace")
            pos += ln
            if field_no == 1:
                req.group_id = val
            elif field_no == 2:
                req.server_id = val
            else:
                req.peer_id = val
        elif field_no in (4, 5, 6) and wire_type == WIRE_VARINT:
            v, pos = _decode_varint(buf, pos)
            if field_no == 4:
                req.term = int(v)
            elif field_no == 5:
                req.prev_log_term = int(v)
            else:
                req.prev_log_index = int(v)
        else:
            pos = _skip_field(buf, pos, wire_type)
    return req


# EntryType mapping from sofa-jraft enum.proto
_ENTRY_TYPE_MAP = {
    "ENTRY_TYPE_UNKNOWN": 0,
    "ENTRY_TYPE_NO_OP": 1,
    "ENTRY_TYPE_DATA": 2,
    "ENTRY_TYPE_CONFIGURATION": 3,
}


def _encode_error_response(err: Dict[str, Any]) -> bytes:
    # message ErrorResponse { required int32 errorCode = 1; optional string errorMsg = 2; }
    out = bytearray()
    if err is None:
        return b""
    code = int(err.get("errorCode", 0))
    out += _encode_key(1, WIRE_VARINT) + _encode_varint(code)
    msg = err.get("errorMsg", "")
    if msg is not None:
        out += _encode_key(2, WIRE_LEN) + _encode_len_delimited(str(msg).encode("utf-8"))
    return bytes(out)


def _encode_entry_meta(entry: Dict[str, Any]) -> bytes:
    """
    message EntryMeta {
      required int64 term = 1;
      required EntryType type = 2;
      repeated string peers = 3;
      optional int64 data_len = 4;
      repeated string old_peers = 5;
      optional int64 checksum = 6;
      repeated string learners = 7;
      repeated string old_learners = 8;
    }
    """
    out = bytearray()

    out += _encode_key(1, WIRE_VARINT) + _encode_varint(int(entry.get("term", 0)))

    t = entry.get("type", 0)
    if isinstance(t, str):
        t = _ENTRY_TYPE_MAP.get(t.upper(), 0)
    out += _encode_key(2, WIRE_VARINT) + _encode_varint(int(t))

    for p in entry.get("peers", []) or []:
        out += _encode_key(3, WIRE_LEN) + _encode_len_delimited(str(p).encode("utf-8"))

    if "data_len" in entry:
        out += _encode_key(4, WIRE_VARINT) + _encode_varint(int(entry.get("data_len", 0)))

    for p in entry.get("old_peers", []) or []:
        out += _encode_key(5, WIRE_LEN) + _encode_len_delimited(str(p).encode("utf-8"))

    if "checksum" in entry:
        out += _encode_key(6, WIRE_VARINT) + _encode_varint(int(entry.get("checksum", 0)))

    for p in entry.get("learners", []) or []:
        out += _encode_key(7, WIRE_LEN) + _encode_len_delimited(str(p).encode("utf-8"))

    for p in entry.get("old_learners", []) or []:
        out += _encode_key(8, WIRE_LEN) + _encode_len_delimited(str(p).encode("utf-8"))

    return bytes(out)


def encode_pull_log_entry_response_from_ndn_content(content: bytes) -> bytes:
    """
    Convert NDN Data JSON content into sofa-jraft RpcRequests.PullLogEntryResponse protobuf bytes.
    The JSON shape is produced by our NDN side and matches the fields used in python_project/ndn/server.py.
    """
    data = json.loads(content.decode("utf-8"))

    out = bytearray()
    out += _encode_key(1, WIRE_VARINT) + _encode_varint(int(data.get("term", 0)))
    out += _encode_key(2, WIRE_VARINT) + _encode_varint(1 if data.get("success", False) else 0)

    if "last_log_index" in data:
        out += _encode_key(3, WIRE_VARINT) + _encode_varint(int(data.get("last_log_index", 0)))

    for e in data.get("entries", []) or []:
        em = _encode_entry_meta(e)
        out += _encode_key(4, WIRE_LEN) + _encode_len_delimited(em)

    if "committed_index" in data:
        out += _encode_key(5, WIRE_VARINT) + _encode_varint(int(data.get("committed_index", 0)))

    if "data" in data and data["data"] is not None:
        if isinstance(data["data"], str):
            try:
                raw = base64.b64decode(data["data"])
            except Exception:
                raw = data["data"].encode("utf-8")
        elif isinstance(data["data"], (bytes, bytearray)):
            raw = bytes(data["data"])
        else:
            raw = str(data["data"]).encode("utf-8")
        out += _encode_key(6, WIRE_LEN) + _encode_len_delimited(raw)

    if "errorResponse" in data and data["errorResponse"] is not None:
        er = _encode_error_response(data["errorResponse"])
        # errorResponse = 99
        out += _encode_key(99, WIRE_LEN) + _encode_len_delimited(er)

    return bytes(out)

