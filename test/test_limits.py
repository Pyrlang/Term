"""Resource limits of the decoders (plan step TERM-09) and the encoders
(TERM-22).

Valid terms that are too deep or too big to decode safely fail fast with
``PyCodecError``, the same way in both codecs. OTP itself would decode them;
the limits are ours (options ``max_depth`` and ``max_size``). Malformed
counts and compressed terms that OTP rejects too are in ``test_bad_terms.py``
(``limits.*``). The encoders take the same ``max_depth`` option and refuse
values that contain themselves.
"""

import shutil
import struct
import subprocess
import time
import zlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fixture_manifest import codec_id

from term.list import ImproperList
from term.py_codec_impl import DEFAULT_MAX_DEPTH, DEFAULT_MAX_SIZE

# The Erlang runtime that judges the deep encoding; None skips that test.
ERL = shutil.which("erl")
CHECKER_SRC = Path(__file__).parent / "erl" / "check_roundtrip.erl"

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


def _deep_value(depth: int) -> list[Any]:
    """``[[...[]...]]`` as a Python value: ``depth`` non-empty lists."""
    value: list[Any] = []
    for _ in range(depth):
        value = [value]
    return value


def test_encode_max_depth(codec: ModuleType) -> None:
    """4096 nested lists encode (to the bytes the decoder tests use); one
    more is refused, as by the decoders."""
    data = codec.term_to_binary(_deep_value(DEFAULT_MAX_DEPTH), None)
    assert data == _nested_list(DEFAULT_MAX_DEPTH)
    with pytest.raises(codec.PyCodecError, match="max_depth"):
        codec.term_to_binary(_deep_value(DEFAULT_MAX_DEPTH + 1), None)


@pytest.mark.parametrize(
    "wrap",
    [
        lambda v: [v],
        lambda v: (v,),
        lambda v: {1: v},
        lambda v: ImproperList([1], v),
    ],
    ids=["list", "tuple", "map", "improper_list_tail"],
)
def test_encode_max_depth_option(codec: ModuleType, wrap: Any) -> None:
    """Every open compound value counts: here 10 of a kind around 0."""
    value = 0
    for _ in range(10):
        value = wrap(value)
    codec.term_to_binary(value, {"max_depth": 10})
    with pytest.raises(codec.PyCodecError, match="max_depth"):
        codec.term_to_binary(value, {"max_depth": 9})


def test_encode_deep_bomb(codec: ModuleType) -> None:
    """100 000 nested lists fail fast instead of overflowing a stack."""
    start = time.perf_counter()
    with pytest.raises(codec.PyCodecError, match="max_depth"):
        codec.term_to_binary(_deep_value(100_000), None)
    assert time.perf_counter() - start < FAST


def test_encode_self_containing(codec: ModuleType) -> None:
    lst: list[Any] = [1]
    lst.append(lst)
    with pytest.raises(codec.PyCodecError, match="contains itself"):
        codec.term_to_binary(lst, None)
    dct: dict[Any, Any] = {}
    dct[1] = [dct]
    with pytest.raises(codec.PyCodecError, match="contains itself"):
        codec.term_to_binary(dct, None)


def test_encode_shared_is_not_a_cycle(codec: ModuleType) -> None:
    """The same list twice side by side is not a cycle."""
    shared = [1]
    assert codec.term_to_binary([shared, shared], None) == codec.term_to_binary(
        [[1], [1]], None
    )


class _Endless:
    """Has no encoding; its ``__etf__`` returns another one of itself."""

    def __etf__(self) -> "_Endless":
        return _Endless()


def test_encode_endless_substitution(codec: ModuleType) -> None:
    """Hooks that never return an encodable value fail, not loop."""
    with pytest.raises(codec.PyCodecError, match="max_depth"):
        codec.term_to_binary(_Endless(), None)
    hooks = {"catch_all": lambda v: v}
    with pytest.raises(codec.PyCodecError, match="max_depth"):
        codec.term_to_binary(object(), {"encode_hook": hooks})
    # Hooks that nest the value deeper every time hit the depth limit.
    with pytest.raises(codec.PyCodecError, match="max_depth"):
        codec.term_to_binary(object(), {"encode_hook": {"catch_all": lambda v: [v]}})


@pytest.mark.erlang
@pytest.mark.skipif(ERL is None, reason="erl (Erlang/OTP) is not on PATH")
def test_otp_decodes_deep_encoding(codec: ModuleType, tmp_path: Path) -> None:
    """OTP writes its own 4096-deep list, and check_roundtrip.erl confirms
    that ours decodes to the same term."""
    assert ERL is not None
    theirs = tmp_path / "otp"
    ours = tmp_path / codec_id(codec)
    beam = tmp_path / "beam"
    for d in (theirs, ours, beam):
        d.mkdir()
    (ours / "deep.etf").write_bytes(
        codec.term_to_binary(_deep_value(DEFAULT_MAX_DEPTH), None)
    )
    write_theirs = (
        "T = lists:foldl(fun(_, A) -> [A] end, [], lists:seq(1, %d)), "
        'ok = file:write_file("%s", term_to_binary(T)).'
        % (DEFAULT_MAX_DEPTH, (theirs / "deep.etf").as_posix())
    )
    compile_expr = '{ok, _} = compile:file("%s", [{outdir, "%s"}, report]).' % (
        CHECKER_SRC.as_posix(),
        beam.as_posix(),
    )
    cmd = [ERL, "-noshell", "-pa", beam.as_posix(), "-eval", write_theirs]
    cmd += ["-eval", compile_expr, "-run", "check_roundtrip", "main"]
    cmd += [theirs.as_posix(), ours.as_posix()]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checked\t%s\t1" % ours.as_posix() in proc.stdout
