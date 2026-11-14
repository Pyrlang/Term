"""Resource limits of the decoders (plan step TERM-09).

Valid terms that are too deep or too big to decode safely fail fast with
``PyCodecError``, the same way in both codecs. OTP itself would decode them;
the limits are ours (options ``max_depth`` and ``max_size``). Malformed
counts and compressed terms that OTP rejects too are in ``test_bad_terms.py``
(``limits.*``).
"""

import struct
import time
import zlib
from types import ModuleType
from typing import Any

import pytest

from term.py_codec_impl import DEFAULT_MAX_DEPTH, DEFAULT_MAX_SIZE

# Longest a rejected bomb may take to fail.
FAST = 1.0


def _nested_list(depth: int) -> bytes:
    """``[[...[]...]]``: ``depth`` lists inside each other."""
    return bytes([131]) + bytes([108, 0, 0, 0, 1]) * depth + bytes([106]) * (depth + 1)


def _compressed(declared: int, packed: bytes) -> bytes:
    return bytes([131, 80]) + struct.pack(">I", declared) + packed


def _rejected_fast(codec: ModuleType, data: bytes, options: Any = None) -> str:
    start = time.perf_counter()
    with pytest.raises(codec.PyCodecError) as info:
        codec.binary_to_term(data, options)
    assert time.perf_counter() - start < FAST
    return str(info.value)


def test_depth_bomb(codec: ModuleType) -> None:
    """A list nested 100 000 deep."""
    assert "max_depth" in _rejected_fast(codec, _nested_list(100_000))


def test_default_max_depth(codec: ModuleType) -> None:
    value, _tail = codec.binary_to_term(_nested_list(DEFAULT_MAX_DEPTH), None)
    for _ in range(DEFAULT_MAX_DEPTH - 1):
        value = value[0]
    assert value == [[]]
    _rejected_fast(codec, _nested_list(DEFAULT_MAX_DEPTH + 1))


@pytest.mark.parametrize("opener", [b"h\x01", b"t\x00\x00\x00\x01a\x00"])
def test_max_depth_counts_tuples_and_maps(codec: ModuleType, opener: bytes) -> None:
    """Every open compound term counts: here 10 tuples (or maps) around 0."""
    data = bytes([131]) + opener * 10 + bytes([97, 0])
    codec.binary_to_term(data, {"max_depth": 10})
    _rejected_fast(codec, data, {"max_depth": 9})


def test_zlib_bomb(codec: ModuleType) -> None:
    """16 MiB of zeros declared as 1 KiB: inflating stops after the declared
    size instead of producing all of it."""
    packed = zlib.compress(bytes(16 * 1024 * 1024))
    _rejected_fast(codec, _compressed(1024, packed))


def test_compressed_declaring_4_gib(codec: ModuleType) -> None:
    """Rejected by max_size before anything is inflated."""
    packed = zlib.compress(bytes([106]))
    message = _rejected_fast(codec, _compressed(0xFFFFFFFF, packed))
    assert "max_size" in message


def test_max_size_option(codec: ModuleType) -> None:
    data = bytes([109]) + struct.pack(">I", 995) + bytes(995)  # <<0:995/unit:8>>
    term = _compressed(len(data), zlib.compress(data))
    value, _tail = codec.binary_to_term(term, {"max_size": len(data)})
    assert value == bytes(995)
    _rejected_fast(codec, term, {"max_size": len(data) - 1})
    assert DEFAULT_MAX_SIZE == 256 * 1024 * 1024


@pytest.mark.parametrize("name", ["max_depth", "max_size"])
@pytest.mark.parametrize("value", [0, -1, "10", True, 1.5])
def test_bad_limit_options(codec: ModuleType, name: str, value: Any) -> None:
    with pytest.raises(codec.PyCodecError):
        codec.binary_to_term(bytes([131, 106]), {name: value})
