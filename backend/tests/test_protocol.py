import json

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from vision_input import PROTOCOL_VERSION
from vision_input.server.protocol import (
    HEADER_SIZE,
    PreviewHeader,
    decode_msg,
    encode_msg,
    pack_preview,
    unpack_preview,
)


def test_header_size_is_24():
    assert HEADER_SIZE == 24


@given(
    seq=st.integers(0, 2**32 - 1),
    t=st.floats(0, 4e12, allow_nan=False),
    w=st.integers(1, 65535),
    h=st.integers(1, 65535),
    flags=st.integers(0, 65535),
    payload=st.binary(max_size=64),
)
def test_preview_roundtrip(seq, t, w, h, flags, payload):
    hdr = PreviewHeader(seq, t, w, h, flags)
    got, body = unpack_preview(pack_preview(hdr, payload))
    assert got == hdr and body == payload


def test_preview_rejects_garbage():
    with pytest.raises(ValueError):
        unpack_preview(b"short")
    with pytest.raises(ValueError):
        unpack_preview(b"XXXX" + bytes(40))


def test_json_envelope_and_numpy_values():
    text = encode_msg("state", {"x": np.float32(1.5), "arr": np.arange(3), "s": {1}})
    obj = json.loads(text)
    assert obj == {"v": PROTOCOL_VERSION, "type": "state", "data": {"x": 1.5, "arr": [0, 1, 2], "s": [1]}}
    assert decode_msg(text) == ("state", obj["data"])


@pytest.mark.parametrize("bad", ['[]', '{"v":99,"type":"x"}', '{"v":1}', '{"v":1,"type":"x","data":[1]}'])
def test_decode_rejects_bad_envelopes(bad):
    with pytest.raises(ValueError):
        decode_msg(bad)


def test_encode_refuses_nan():
    with pytest.raises(ValueError):
        encode_msg("x", {"v": float("nan")})
