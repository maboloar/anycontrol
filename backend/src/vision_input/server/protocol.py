"""WebSocket 프로토콜.

- 바이너리 메시지 = 미리보기 프레임: 24바이트 헤더 + JPEG
    magic  4s  b"VIF1"
    ver    u8  PROTOCOL_VERSION
    kind   u8  1 = preview JPEG
    flags  u16 bit0 = mirrored (예약)
    seq    u32 소스 프레임 번호
    t_wall f64 캡처 시각 (unix ms)
    width  u16 JPEG 가로
    height u16 JPEG 세로
- 텍스트 메시지 = JSON {"v": 1, "type": str, "data": {...}}
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

from .. import PROTOCOL_VERSION

MAGIC = b"VIF1"
HEADER = struct.Struct("<4sBBHIdHH")
HEADER_SIZE = HEADER.size  # 24
KIND_PREVIEW = 1


@dataclass(frozen=True, slots=True)
class PreviewHeader:
    seq: int
    t_wall_ms: float
    width: int
    height: int
    flags: int = 0


def pack_preview(h: PreviewHeader, jpeg: bytes) -> bytes:
    return HEADER.pack(MAGIC, PROTOCOL_VERSION, KIND_PREVIEW, h.flags, h.seq & 0xFFFFFFFF,
                       h.t_wall_ms, h.width, h.height) + jpeg


def unpack_preview(buf: bytes) -> tuple[PreviewHeader, bytes]:
    if len(buf) < HEADER_SIZE:
        raise ValueError("buffer shorter than header")
    magic, ver, kind, flags, seq, t_wall, w, h = HEADER.unpack_from(buf)
    if magic != MAGIC:
        raise ValueError("bad magic")
    if ver != PROTOCOL_VERSION or kind != KIND_PREVIEW:
        raise ValueError(f"unsupported version/kind {ver}/{kind}")
    return PreviewHeader(seq, t_wall, w, h, flags), buf[HEADER_SIZE:]


def encode_msg(type_: str, data: Any) -> str:
    return json.dumps({"v": PROTOCOL_VERSION, "type": type_, "data": data},
                      ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_default)


def decode_msg(text: str) -> tuple[str, dict[str, Any]]:
    obj = json.loads(text)
    if not isinstance(obj, dict) or obj.get("v") != PROTOCOL_VERSION or not isinstance(obj.get("type"), str):
        raise ValueError("invalid message envelope")
    data = obj.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    return obj["type"], data


def _default(o: Any) -> Any:
    # numpy 스칼라·배열 등
    if hasattr(o, "tolist"):
        return o.tolist()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")
