"""Encoding tests; each runs against the Python and the native codec."""

from types import ModuleType

import pytest

from term import codec as default_impl
from term import py_codec_impl as py_impl
from term.atom import Atom, StrictAtom
from term.bitstring import BitString
from term.list import ImproperList
from term.pid import Pid
from term.reference import Reference

# Atom classes the atom encoding tests run with; both encode the same way.
ATOM_CLASSES = [
    pytest.param(Atom, id="Atom"),
    pytest.param(StrictAtom, id="StrictAtom"),
]


@pytest.mark.parametrize("atom_cls", ATOM_CLASSES)
def test_encode_atom(codec: ModuleType, atom_cls: type[Atom]) -> None:
    """Try an atom 'hello' encoded as Latin1 atom (16-bit length)
    or small atom (8bit length)
    """
    # Create and encode 'hello...hello' 52 times (260 bytes)
    # Expect UTF8 back because encoder only does UTF8 atoms
    repeat1 = 52
    example1 = bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_ATOM_UTF8_EXT, 1, 4]) + (
        b"hello" * repeat1
    )
    b1 = codec.term_to_binary(atom_cls("hello" * repeat1), None)
    assert b1 == example1

    # Create and encode 'hello...hello' 5 times (25 bytes)
    repeat2 = 5
    example2 = bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 25]) + (
        b"hello" * repeat2
    )
    b2 = codec.term_to_binary(atom_cls("hello" * repeat2), None)
    assert b2 == example2


@pytest.mark.parametrize("atom_cls", ATOM_CLASSES)
def test_encode_atom_utf8(codec: ModuleType, atom_cls: type[Atom]) -> None:
    # Create and encode 'hallå...hallå' 50 times (300 bytes)
    repeat1 = 50
    example1 = bytes(
        [py_impl.ETF_VERSION_TAG, py_impl.TAG_ATOM_UTF8_EXT, 1, (300 - 256)]
    ) + (bytes("hallå", "utf8") * repeat1)
    b1 = codec.term_to_binary(atom_cls("hallå" * repeat1), None)
    assert b1 == example1

    # Create and encode 'hallå...hallå' 5 times (30 bytes)
    repeat2 = 5
    example2 = bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 30]) + (
        bytes("hallå", "utf8") * repeat2
    )
    b2 = codec.term_to_binary(atom_cls("hallå" * repeat2), None)
    assert b2 == example2


def test_encode_str(codec: ModuleType) -> None:
    # A 8-bit string max 65535 characters, optimized as byte array
    byte_example = bytes(
        [py_impl.ETF_VERSION_TAG, py_impl.TAG_STRING_EXT, 0, 5]
    ) + bytes("hello", "latin-1")

    b1 = codec.term_to_binary("hello", None)
    assert b1 == byte_example


def test_encode_str_unicode(codec: ModuleType) -> None:
    # Unicode value for <A with RING ABOVE> is still within byte range
    # so this will produce a list of small ints
    unicode_example1 = bytes(
        [py_impl.ETF_VERSION_TAG, py_impl.TAG_STRING_EXT, 0, 6]
    ) + "hallå".encode("utf8")

    # unicode but codepoints <= 255
    b1 = codec.term_to_binary("hallå", None)
    assert b1 == unicode_example1

    unicode_example2 = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_LIST_EXT,
            0,
            0,
            0,
            2,
            py_impl.TAG_INT,
            0,
            0,
            3,
            148,
            py_impl.TAG_INT,
            0,
            0,
            3,
            169,
            py_impl.TAG_NIL_EXT,
        ]
    )

    # unicode with large codepoints
    b2 = codec.term_to_binary("ΔΩ", None)
    assert b2 == unicode_example2


def test_encode_tuple(codec: ModuleType) -> None:
    """Encode a tuple"""
    example1 = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_SMALL_TUPLE_EXT,
            2,  # length
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_SMALL_ATOM_UTF8_EXT,
            2,
            111,
            107,
        ]
    )
    b1 = codec.term_to_binary((1, Atom("ok")), None)
    assert b1 == example1


def test_encode_list(codec: ModuleType) -> None:
    """Encode list of something, an improper list and an empty list."""
    example1 = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_LIST_EXT,
            0,
            0,
            0,
            2,  # length
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_SMALL_ATOM_UTF8_EXT,
            2,
            111,
            107,
            py_impl.TAG_NIL_EXT,
        ]
    )
    b1 = codec.term_to_binary([1, Atom("ok")], None)
    assert b1 == example1

    example2 = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_LIST_EXT,
            0,
            0,
            0,
            1,  # length
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_SMALL_ATOM_UTF8_EXT,
            2,
            111,
            107,
        ]
    )
    b2 = codec.term_to_binary(ImproperList([1], Atom("ok")), None)
    assert b2 == example2


def test_encode_map(codec: ModuleType) -> None:
    """Try a map #{1 => 2, ok => error}"""
    sample = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_MAP_EXT,
            0,
            0,
            0,
            2,
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_SMALL_INT,
            2,
            py_impl.TAG_SMALL_ATOM_UTF8_EXT,
            2,
            111,
            107,
            py_impl.TAG_SMALL_ATOM_UTF8_EXT,
            5,
            101,
            114,
            114,
            111,
            114,
        ]
    )
    val = {1: 2, Atom("ok"): Atom("error")}
    bin1 = codec.term_to_binary(val, None)
    assert bin1 == sample


def test_encode_pid(codec: ModuleType) -> None:
    sample1 = (
        bytes(
            [
                py_impl.ETF_VERSION_TAG,
                py_impl.TAG_NEW_PID_EXT,
                py_impl.TAG_SMALL_ATOM_UTF8_EXT,
                13,
            ]
        )
        + bytes("nonode@nohost", "latin-1")
        + bytes([0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 3])
    )
    val = Pid("nonode@nohost", 1, 2, 3)
    bin1 = codec.term_to_binary(val, None)
    assert bin1 == sample1


def test_encode_ref(codec: ModuleType) -> None:
    creation = 1
    sample1 = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_NEWER_REF_EXT,
            0,
            3,  # length
            py_impl.TAG_SMALL_ATOM_UTF8_EXT,
            13,
            110,
            111,
            110,
            111,
            100,
            101,
            64,
            110,
            111,
            104,
            111,
            115,
            116,
            0,
            0,
            0,
            creation,
        ]
    ) + bytes("fgsfdsfdsfgs", "latin-1")

    val = Reference("nonode@nohost", creation, b"fgsfdsfdsfgs")
    bin1 = codec.term_to_binary(val, None)
    assert bin1 == sample1


def test_encode_float(codec: ModuleType) -> None:
    example1 = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_NEW_FLOAT_EXT,  # a 8-byte IEEE double
            64,
            9,
            33,
            251,
            84,
            68,
            45,
            17,
        ]
    )
    b1 = codec.term_to_binary(3.14159265358979, None)
    assert b1 == example1


def test_encode_int(codec: ModuleType) -> None:
    positive = bytes([131, 98, 0, 0, 18, 139])  # 4747
    negative = bytes([131, 98, 255, 255, 237, 117])  # -4747
    b1 = codec.term_to_binary(4747, None)
    b2 = codec.term_to_binary(-4747, None)
    assert b1 == positive
    assert b2 == negative


def test_encode_small_big(codec: ModuleType) -> None:
    # Bigger then 4 bytes lt 256
    positive = bytes([131, 110, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # 2 ** 64
    negative = bytes([131, 110, 9, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # - (2 ** 64)
    b1 = codec.term_to_binary(2**64, None)
    b2 = codec.term_to_binary(-(2**64), None)
    assert b1 == positive
    assert b2 == negative


def test_encode_small_big_random_bytes(codec: ModuleType) -> None:
    positive = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_SMALL_BIG_EXT,
            13,
            0,
            210,
            10,
            63,
            78,
            238,
            224,
            115,
            195,
            246,
            15,
            233,
            142,
            1,
        ]
    )
    negative = bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_SMALL_BIG_EXT,
            13,
            1,
            210,
            10,
            63,
            78,
            238,
            224,
            115,
            195,
            246,
            15,
            233,
            142,
            1,
        ]
    )
    b1 = codec.term_to_binary(123456789012345678901234567890, None)
    b2 = codec.term_to_binary(-123456789012345678901234567890, None)
    assert b1 == positive
    assert b2 == negative


def test_encode_large_big(codec: ModuleType) -> None:
    # 256 bytes of int or more
    positive = bytes(
        [
            131,
            111,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
        ]
    )  # 2 ** 2040
    negative = bytes(
        [
            131,
            111,
            0,
            0,
            1,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
        ]
    )  # - (2 ** 2040)
    b1 = codec.term_to_binary(2**2040, None)
    b2 = codec.term_to_binary(-(2**2040), None)
    assert b1 == positive
    assert b2 == negative


def test_encode_binary(codec: ModuleType) -> None:
    waagh = bytes("Waagh", "latin-1")
    example1 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_BINARY_EXT, 0, 0, 0, 5]) + waagh
    )
    b1 = codec.term_to_binary(waagh, None)
    assert b1 == example1

    example2 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_BIT_BINARY_EXT, 0, 0, 0, 5, 4])
        + waagh
    )
    b2 = codec.term_to_binary(BitString(val=waagh, last_byte_bits=4), None)
    assert b2 == example2


def test_encode_special(codec: ModuleType) -> None:
    """Test encoding true, false, undefined=None"""
    example1 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 4]) + b"true"
    )
    data1 = codec.term_to_binary(True, None)
    assert data1 == example1

    example2 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 5]) + b"false"
    )
    data2 = codec.term_to_binary(False, None)
    assert data2 == example2

    example3 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 9])
        + b"undefined"
    )
    data3 = codec.term_to_binary(None, None)
    assert data3 == example3


def test_encode_catch_all_fn(codec: ModuleType) -> None:
    """Tries to encode a special class CustomClass, and converts it to
    atom 'custom-hook!' using a hook function.
    """

    class Class1:
        pass

    def catch_all_fn(obj: object) -> Atom | None:
        """This function will fire if "encode_hook" is passed in encode
        options dict with the key "catch_all" present.
        """
        if isinstance(obj, Class1):
            return Atom("custom-hook!")
        return None

    example1 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 12])
        + b"custom-hook!"
    )
    data1 = codec.term_to_binary(Class1(), {"encode_hook": {"catch_all": catch_all_fn}})
    assert data1 == example1


def test_encode_catch_all_fn_legacy() -> None:
    """Previous format of encode hook is deprecated when accessing the native
    or py codecs explicitly. If accessed using the decorators in codec.py,
    encode_hook=hook, will be transformed into a dict {'catch_all': hook}.
    """
    _catch_all_legacy(default_impl)


def _catch_all_legacy(codec: ModuleType) -> None:
    """Tries to encode a special class CustomClass, and converts it to
    atom 'custom-hook!' using a hook function.
    """

    class Class1:
        pass

    def catch_all_fn(obj: object) -> Atom | None:
        """This function will fire if "encode_hook" is passed in encode
        options dict.
        """
        if isinstance(obj, Class1):
            return Atom("custom-hook!")
        return None

    example1 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 12])
        + b"custom-hook!"
    )
    data1 = codec.term_to_binary(Class1(), {"encode_hook": catch_all_fn})
    assert data1 == example1


def test_encode_hook_fn(codec: ModuleType) -> None:
    """tries to encode a float by first casting it to int using an encode hook."""

    def float_to_int_override_fn(obj: object) -> int | None:
        """this function will fire for each float in encode, if "encode_hook"
        is passed in encode options dict
        """
        if isinstance(obj, float):
            return int(obj)
        return None

    example1 = bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_INT, 5])
    data1 = codec.term_to_binary(
        5.0, {"encode_hook": {"float": float_to_int_override_fn}}
    )

    assert data1 == example1


def test_encode_hook_member(codec: ModuleType) -> None:
    """Tries to encode a special class CustomClass, and converts it to
    atom 'custom-member!' using a class member hook function.
    """

    class Class1:
        def __etf__(self) -> Atom:
            """This function will fire if no "encode_hook" was passed in
            options, and the library doesn't know what to do with this
            'CustomClass'
            """
            return Atom("custom-member!")

    # Encode hook is a method of the class, named __etf__
    example2 = (
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 14])
        + b"custom-member!"
    )
    data2 = codec.term_to_binary(Class1(), None)
    assert data2 == example2


def test_encode_hook_missing(codec: ModuleType) -> None:
    """Tries to encode a special class Class3 without an encode hook"""

    # A custom class without a hook, should be encoded as a dictionary
    # with {'ClassName', #{fields}}
    class Class3:
        def __init__(self) -> None:
            self.field1 = 1

    val3 = Class3()
    repr3 = (b"Class3", {b"field1": 1})
    example3 = codec.term_to_binary(repr3, None)
    data3 = codec.term_to_binary(val3, None)
    assert data3 == example3


def test_fail_encode_nonfinite_float(codec: ModuleType) -> None:
    # Check that nonfinites raise exception, even when within a list, tuple
    # or dict
    nonfinites = [float(n) for n in "inf -inf nan".split()]
    for n in nonfinites:
        with pytest.raises(Exception):
            codec.term_to_binary(n)


def test_fail_encode_nested_nonfinite_float(codec: ModuleType) -> None:
    # Check that nonfinites raise exception, even when within a list, tuple
    # or dict
    nonfinites = [{1: float("inf")}, [2, float("-inf")], (3, float("nan"))]
    for n in nonfinites:
        with pytest.raises(Exception):
            codec.term_to_binary(n)
