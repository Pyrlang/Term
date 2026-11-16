"""Decode and encode the golden fixtures that real OTP wrote (plan step TERM-03).

The fixtures in ``test/fixtures`` come from ``test/erl/gen_fixtures.erl``;
``MANIFEST.tsv`` lists them. Both codecs run every test:

- decode: every fixture decodes, consumes all its bytes, and, where
  ``EXPECTED`` defines the Python value, gives exactly that value (same
  types, same float sign);
- encode: every value in ``EXPECTED`` encodes to exactly OTP's bytes.
"""

import struct
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from term import py_codec_impl
from term.atom import Atom
from term.bitstring import BitString
from term.fun import Export
from term.list import ImproperList
from term.pid import Pid
from term.port import Port
from term.record import Record
from term.reference import Reference

# Where gen_fixtures.erl writes its output.
FIXTURE_DIR = Path(__file__).parent / "fixtures"


# One line of MANIFEST.tsv.
@dataclass(frozen=True)
class _Fixture:
    name: str
    otp_release: str
    stability: str
    source: str
    options: str
    # Used by test_roundtrip.py (fixture_manifest.py); not by this file.
    features: str


def _load_manifest() -> list[_Fixture]:
    lines = (FIXTURE_DIR / "MANIFEST.tsv").read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    assert header == [
        "name",
        "otp_release",
        "stability",
        "source",
        "options",
        "features",
    ]
    return [_Fixture(*line.split("\t")) for line in lines[1:]]


FIXTURES = _load_manifest()

# Fixtures that neither codec decodes yet, and the plan step that fixes them.
NOT_DECODED: dict[str, str] = {}

# Fixtures that one codec does not decode yet: (name, codec id) -> plan step.
NOT_DECODED_BY: dict[tuple[str, str], str] = {}

# Terms with no Python value (a map key that a dict cannot hold, map keys
# that are one key in Python), and LOCAL_EXT, which only the node that wrote
# it can decode: decoding must raise PyCodecError.
REJECTED = {
    "map_list_key",
    "map_map_key",
    "map_int_float_key",
    "map_true_int_key",
    "map_tuple_int_float_key",
    "map_zero_keys",
    "map_atom_string_key",
    "local_ext",
}

# Rejections that one codec gets wrong yet: (name, codec id) -> plan step.
REJECTED_WRONGLY_BY: dict[tuple[str, str], str] = {}

_FIX_NODE = Atom("fix@host")


def _rec(name: str, exported: bool, **fields: Any) -> Record:
    """A native record of module gen_fixtures."""
    return Record(
        Atom("gen_fixtures"),
        Atom(name),
        exported,
        {Atom(k): v for k, v in fields.items()},
    )


# Key order of fixture map_33 (more than 32 keys: OTP's internal hash order).
_MAP_33_OTP_ORDER = [22, 26, 27, 5, 21, 30, 16, 3, 33, 14, 24, 17, 11, 6, 20, 28]
_MAP_33_OTP_ORDER += [25, 1, 32, 15, 9, 23, 10, 8, 31, 7, 2, 13, 29, 19, 12, 4, 18]

# Exact decoded values with the default options, for every fixture whose
# Python representation is already defined.
EXPECTED: dict[str, Any] = {
    "int_0": 0,
    "int_255": 255,
    "int_256": 256,
    "int_neg_1": -1,
    "int_2p31_minus_1": 2**31 - 1,
    "int_neg_2p31": -(2**31),
    "int_neg_2p31_minus_1": -(2**31) - 1,
    "int_2p31": 2**31,
    "int_2p32_minus_1": 2**32 - 1,
    "int_2p32": 2**32,
    "int_2p64": 2**64,
    "int_neg_2p64": -(2**64),
    "int_2p2039": 2**2039,
    "int_2p2040_minus_1": 2**2040 - 1,
    "int_2p2040": 2**2040,
    "float_0": 0.0,
    "float_neg_0": -0.0,
    "float_1_5": 1.5,
    "float_1e308": 1.0e308,
    "float_1_5_minor_0": 1.5,
    "atom_empty": Atom(""),
    "atom_ascii": Atom("hello"),
    "atom_latin1": Atom("é"),
    "atom_utf8": Atom("при"),
    "atom_255_ascii": Atom("a" * 255),
    "atom_255_4byte": Atom("\U0001f600" * 255),
    "atom_empty_minor_1": Atom(""),
    "atom_ascii_minor_1": Atom("hello"),
    "atom_latin1_minor_1": Atom("é"),
    "atom_utf8_minor_1": Atom("при"),
    "atom_255_ascii_minor_1": Atom("a" * 255),
    "atom_255_4byte_minor_1": Atom("\U0001f600" * 255),
    "str_empty": [],
    "str_abc": "abc",
    "str_latin1": "é",
    "str_65535": "a" * 65535,
    "str_65536": [ord("a")] * 65536,
    "str_wide": [ord("a"), 256, ord("b")],
    "list_proper": [Atom("a"), 1, (Atom("b"),)],
    "list_nested": [[Atom("a"), [Atom("b")]], [], [Atom("c")]],
    "list_improper": ImproperList([1], 2),
    "tuple_0": (),
    "tuple_255": tuple(range(1, 256)),
    "tuple_256": tuple(range(1, 257)),
    "map_0": {},
    "map_32": {k: k for k in range(1, 33)},
    # Keys in the order OTP 29 wrote this hash map, so that encoding the dict
    # (which keeps insertion order) can reproduce OTP's bytes.
    "map_33": {k: k for k in _MAP_33_OTP_ORDER},
    "bin_empty": b"",
    "bin_1_2_3": b"\x01\x02\x03",
    # Bitstrings decode to (bytes, bits in the last byte) until TERM-20.
    "bits_1_1": (b"\x80", 1),
    "bits_5_7": (b"\x0a", 7),
    "bits_1_2_3_4": (b"\x01\x02\x30", 4),
    "compressed_list": [(Atom("hello"), b"world")] * 200,
    "pid_small": Pid(_FIX_NODE, 1, 2, 3),
    "pid_max": Pid(_FIX_NODE, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),
    # Fed in as NEW_PORT_EXT, V4_PORT_EXT; OTP 29 writes all as V4_PORT_EXT.
    "port_2p28_minus_1": Port(_FIX_NODE, 2**28 - 1, 1),
    "port_2p28": Port(_FIX_NODE, 2**28, 1),
    "port_2p64_minus_1": Port(_FIX_NODE, 2**64 - 1, 0xFFFFFFFF),
    "fun_export": Export(Atom("lists"), Atom("map"), 2),
    # Native records (OTP 29) of module gen_fixtures; fields in definition order.
    # [1, 2] is written as STRING_EXT, which decodes to str.
    "record_exported": _rec("fix_exported", True, a=1, b="\x01\x02"),
    "record_local": _rec("fix_local", False, x=(1, 2), y=[]),
    "record_empty": _rec("fix_empty", False),
    "record_nested": _rec(
        "fix_exported",
        True,
        a=_rec("fix_local", False, x=_rec("fix_empty", False), y=[]),
        b=Atom("two"),
    ),
    "ref_1_word": Reference(_FIX_NODE, 1, struct.pack(">I", 1)),
    "ref_3_words": Reference(_FIX_NODE, 1, struct.pack(">3I", 1, 2, 3)),
    "ref_5_words": Reference(_FIX_NODE, 1, struct.pack(">5I", 1, 2, 3, 4, 5)),
    "ref_max_creation": Reference(_FIX_NODE, 0xFFFFFFFF, b"\xff" * 12),
}

# Values to encode where the decoded representation does not encode back to
# the same term: a bitstring decodes to a tuple (until TERM-20), but only a
# BitString encodes as BIT_BINARY_EXT.
ENCODE_FROM: dict[str, Any] = {
    "bits_1_1": BitString(b"\x80", 1),
    "bits_5_7": BitString(b"\x0a", 7),
    "bits_1_2_3_4": BitString(b"\x01\x02\x30", 4),
}

# Fixtures whose bytes the encoders are tested against: those with a defined
# value, written without term_to_binary options. Our encoders offer no
# {minor_version, N} or compressed output, so those fixtures are decode-only.
ENCODE_FIXTURES = [f for f in FIXTURES if f.name in EXPECTED and f.options == "[]"]

# Fixtures that neither encoder reproduces yet, and the plan step that fixes them.
NOT_ENCODED: dict[str, str] = {}

# Fixtures that one encoder does not reproduce yet: (name, codec id) -> step.
NOT_ENCODED_BY: dict[tuple[str, str], str] = {}

# More values that must encode to a fixture's bytes: a Python str is a list
# of code points, so these give the same bytes as the list in EXPECTED.
ENCODE_ALSO: dict[str, Any] = {
    "str_empty": "",
    "str_65536": "a" * 65536,
    "str_wide": "aĀb",
}


def _codec_id(codec: ModuleType) -> str:
    return "py" if codec is py_codec_impl else "native"


def _assert_same(actual: Any, expected: Any, where: str = "value") -> None:
    """Equal values of the same exact types; floats compared bit for bit."""
    assert type(actual) is type(expected), "%s: %r is not a %s" % (
        where,
        actual,
        type(expected).__name__,
    )
    if isinstance(expected, float):
        assert struct.pack(">d", actual) == struct.pack(">d", expected), where
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected), "%s: length" % where
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_same(a, e, "%s[%d]" % (where, i))
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys(), "%s: keys" % where
        for k, e in expected.items():
            _assert_same(actual[k], e, "%s[%r]" % (where, k))
    else:
        assert actual == expected, where


def test_manifest_matches_files() -> None:
    """Every fixture file is in the manifest and every manifest entry exists."""
    on_disk = {p.stem for p in FIXTURE_DIR.glob("*.etf")}
    listed = [f.name for f in FIXTURES]
    assert len(listed) == len(set(listed))
    assert on_disk == set(listed)


def test_expected_names_exist() -> None:
    """The tables above name only fixtures that the manifest lists."""
    names = {f.name for f in FIXTURES}
    named = set(EXPECTED) | set(NOT_DECODED) | REJECTED
    named |= {n for n, _ in NOT_DECODED_BY} | {n for n, _ in REJECTED_WRONGLY_BY}
    assert named <= names
    encoded = {f.name for f in ENCODE_FIXTURES}
    named_enc = set(ENCODE_FROM) | set(NOT_ENCODED) | {n for n, _ in NOT_ENCODED_BY}
    named_enc |= set(ENCODE_ALSO)
    assert named_enc <= encoded


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_decode_fixture(
    fixture: _Fixture, codec: ModuleType, request: pytest.FixtureRequest
) -> None:
    name = fixture.name
    codec_id = _codec_id(codec)
    data = (FIXTURE_DIR / (name + ".etf")).read_bytes()

    if name in REJECTED:
        step = REJECTED_WRONGLY_BY.get((name, codec_id))
        if step is not None:
            request.applymarker(pytest.mark.xfail(strict=True, reason=step))
        with pytest.raises(codec.PyCodecError):
            codec.binary_to_term(data, None)
        return

    step = NOT_DECODED.get(name) or NOT_DECODED_BY.get((name, codec_id))
    if step is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=step))

    value, tail = codec.binary_to_term(data, None)
    assert tail == b""
    if name in EXPECTED:
        _assert_same(value, EXPECTED[name])


@pytest.mark.parametrize(
    "fixture", ENCODE_FIXTURES, ids=[f.name for f in ENCODE_FIXTURES]
)
def test_encode_fixture(
    fixture: _Fixture, codec: ModuleType, request: pytest.FixtureRequest
) -> None:
    name = fixture.name
    step = NOT_ENCODED.get(name) or NOT_ENCODED_BY.get((name, _codec_id(codec)))
    if step is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=step))

    value = ENCODE_FROM.get(name, EXPECTED[name])
    expected = (FIXTURE_DIR / (name + ".etf")).read_bytes()
    assert codec.term_to_binary(value, None) == expected


@pytest.mark.parametrize("name", list(ENCODE_ALSO))
def test_encode_also(name: str, codec: ModuleType) -> None:
    expected = (FIXTURE_DIR / (name + ".etf")).read_bytes()
    assert codec.term_to_binary(ENCODE_ALSO[name], None) == expected


# The bitstring fixtures and their value as BitString (TERM-20).
BITSTRINGS = {
    name: ENCODE_FROM[name] for name in ("bits_1_1", "bits_5_7", "bits_1_2_3_4")
}


@pytest.mark.parametrize("option", ["tuple", "BitString"])
@pytest.mark.parametrize("name", list(BITSTRINGS))
def test_decode_bitstring_option(name: str, option: str, codec: ModuleType) -> None:
    """Option "bitstring" picks the representation; BitString encodes back
    to OTP's bytes."""
    data = (FIXTURE_DIR / (name + ".etf")).read_bytes()
    value, tail = codec.binary_to_term(data, {"bitstring": option})
    assert tail == b""
    if option == "tuple":
        _assert_same(value, EXPECTED[name])
    else:
        _assert_same(value, BITSTRINGS[name])
        assert codec.term_to_binary(value, None) == data
