"""Decoding tests; each runs against the Python and the native codec."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from term import py_codec_impl as py_impl
from term.atom import Atom, StrictAtom
from term.bitstring import BitString
from term.fun import Fun
from term.list import ImproperList, list_to_unicode_str
from term.pid import Pid
from term.reference import Reference

# The golden fixtures written by OTP (TERM-03).
FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Sentinel used to verify that post-decoded tails are preserved properly
EXPECTED_TAIL_BYTES = bytes([1, 2, 3, 4, 5])


def _etf_bytes(b: bytes | list[int]) -> bytes:
    return bytes(b) + EXPECTED_TAIL_BYTES


def _assert_expected_tail(tail: bytes) -> None:
    assert tail == EXPECTED_TAIL_BYTES


def test_decode_atom(codec: ModuleType) -> None:
    """Try an atom 'hello' encoded as Latin1 atom (16-bit length)
    or small atom (8bit length)
    """
    b1 = _etf_bytes([131, py_impl.TAG_ATOM_EXT, 0, 5, 104, 101, 108, 108, 111])
    t1, tail1 = codec.binary_to_term(b1, None)
    assert isinstance(t1, Atom), "Result must be Atom object"
    assert t1 == "hello"
    _assert_expected_tail(tail1)

    b2 = _etf_bytes([131, py_impl.TAG_SMALL_ATOM_EXT, 5, 104, 101, 108, 108, 111])
    t2, tail2 = codec.binary_to_term(b2, None)
    assert isinstance(t2, Atom), "Result must be Atom object"
    assert t2 == "hello"
    _assert_expected_tail(tail2)


def test_decode_atom_utf8(codec: ModuleType) -> None:
    b1 = _etf_bytes(
        [131, py_impl.TAG_ATOM_UTF8_EXT, 0, 6, 108, 195, 164, 103, 101, 116]
    )
    t1, tail1 = codec.binary_to_term(b1, None)
    assert isinstance(t1, Atom), "Result must be Atom object"
    assert isinstance(t1, str), "Result must be str"
    assert t1 == "läget"
    _assert_expected_tail(tail1)


def test_decode_atom_as_string(codec: ModuleType) -> None:
    """Try an atom 'hello' to a Python string"""
    b1 = _etf_bytes([131, py_impl.TAG_ATOM_EXT, 0, 5, 104, 101, 108, 108, 111])
    t2, tail2 = codec.binary_to_term(b1, {"atom": "str"})
    assert isinstance(t2, str), "Expected str, have: " + t2.__class__.__name__
    assert t2 == "hello"
    _assert_expected_tail(tail2)

    t3, tail3 = codec.binary_to_term(b1, {"atom": "bytes"})
    assert isinstance(t3, bytes), "Expected bytes, have: " + t3.__class__.__name__
    assert t3 == b"hello"
    _assert_expected_tail(tail3)


def test_decode_atom_as_strict(codec: ModuleType) -> None:
    b1 = _etf_bytes([131, py_impl.TAG_ATOM_EXT, 0, 5, 104, 101, 108, 108, 111])
    t1, tail1 = codec.binary_to_term(b1, {"atom": "StrictAtom"})
    assert isinstance(t1, StrictAtom), "Result must be StrictAtom " "got {}".format(
        type(t1)
    )
    assert t1 == "hello"
    _assert_expected_tail(tail1)

    b2 = _etf_bytes([131, py_impl.TAG_SMALL_ATOM_EXT, 5, 104, 101, 108, 108, 111])
    t2, tail2 = codec.binary_to_term(b2, {"atom": "StrictAtom"})
    assert isinstance(t2, StrictAtom), "Result must be Atom " "object"
    assert t2 == "hello"
    _assert_expected_tail(tail2)


def test_decode_atom_custom_callable(codec: ModuleType) -> None:
    b1 = _etf_bytes([131, py_impl.TAG_ATOM_EXT, 0, 5, 104, 101, 108, 108, 111])

    def a_fun(x: str) -> bytes:
        return bytes(x.encode("utf8"))

    t1, tail1 = codec.binary_to_term(b1, {"atom_call": a_fun})
    assert isinstance(t1, bytes)
    assert t1 == b"hello"
    _assert_expected_tail(tail1)


def test_decode_atom_custom_class(codec: ModuleType) -> None:

    b1 = _etf_bytes([131, py_impl.TAG_ATOM_EXT, 0, 5, 104, 101, 108, 108, 111])

    class A(str):
        pass

    class B:
        def __init__(self, text: str) -> None:
            self._text = text

    t1, tail1 = codec.binary_to_term(b1, {"atom_call": str})
    assert isinstance(t1, str)
    assert t1 == "hello"
    _assert_expected_tail(tail1)

    t2, tail2 = codec.binary_to_term(b1, {"atom_call": A})
    assert isinstance(t2, str)
    assert isinstance(t2, A)
    assert t2 == "hello"
    _assert_expected_tail(tail2)

    t3, tail3 = codec.binary_to_term(b1, {"atom_call": B})
    assert isinstance(t3, B)
    assert t3._text == "hello"
    _assert_expected_tail(tail3)


def test_ref_count_leak_on_custom_atom(native_codec: ModuleType) -> None:
    b = _etf_bytes([131, py_impl.TAG_ATOM_EXT, 0, 5, 104, 101, 108, 108, 111])

    def test_fun(codec: ModuleType, b_data: bytes) -> tuple[str, bytes]:
        class A(str):
            pass

        res: tuple[str, bytes] = codec.binary_to_term(b_data, {"atom_call": A})
        return res

    for i in range(10):
        p_res, p_tail = test_fun(py_impl, b)
        n_res, n_tail = test_fun(native_codec, b)

    p_type = type(p_res)
    p_type_refs = sys.getrefcount(p_type)
    n_type = type(n_res)
    n_type_refs = sys.getrefcount(n_type)
    assert p_res == n_res
    assert p_tail == n_tail
    assert p_type != n_type
    assert p_type_refs == n_type_refs


def test_decode_str_ascii(codec: ModuleType) -> None:
    """A string with bytes, encoded as optimized byte array."""
    b1 = _etf_bytes([131, py_impl.TAG_STRING_EXT, 0, 5, 104, 101, 108, 108, 111])
    t1, tail1 = codec.binary_to_term(b1, None)
    assert isinstance(t1, str), "Result must be str"
    assert t1 == "hello"
    _assert_expected_tail(tail1)

    t2, tail2 = codec.binary_to_term(b1, {"byte_string": "bytes"})
    assert isinstance(t2, bytes), "Result must be bytes, got " + t2.__class__.__name__
    assert t2 == b"hello"
    _assert_expected_tail(tail2)


def test_decode_str_unicode(codec: ModuleType) -> None:
    """A string with emoji, encoded as a list of unicode integers."""
    b1 = _etf_bytes(
        [
            131,
            py_impl.TAG_LIST_EXT,
            0,
            0,
            0,
            3,  # length
            py_impl.TAG_INT,
            0,
            0,
            38,
            34,  # 32-bit radiation hazard
            py_impl.TAG_SMALL_INT,
            32,  # 8-bit space (32)
            py_impl.TAG_INT,
            0,
            0,
            38,
            35,  # 32-bit bio-hazard
            py_impl.TAG_NIL_EXT,  # list tail: NIL
        ]
    )
    t1, tail = codec.binary_to_term(b1, None)
    assert isinstance(t1, list), "Result must be a list"
    assert list_to_unicode_str(t1) == "☢ ☣"
    _assert_expected_tail(tail)


def test_decode_str_int_list(codec: ModuleType) -> None:
    """A string with bytes, encoded as optimized byte array."""
    b1 = _etf_bytes([131, py_impl.TAG_STRING_EXT, 0, 5, 104, 101, 108, 108, 111])
    t1, tail1 = codec.binary_to_term(b1, {"byte_string": "int_list"})
    assert t1 == [104, 101, 108, 108, 111]
    _assert_expected_tail(tail1)


def test_decode_pid(codec: ModuleType) -> None:
    """Try a pid"""
    data = _etf_bytes(
        [
            131,
            103,
            100,
            0,
            13,
            101,
            114,
            108,
            64,
            49,
            50,
            55,
            46,
            48,
            46,
            48,
            46,
            49,
            0,
            0,
            0,
            64,
            0,
            0,
            0,
            0,
            1,
        ]
    )
    val, tail = codec.binary_to_term(data, None)
    assert isinstance(val, Pid)
    _assert_expected_tail(tail)


def test_decode_new_pid(codec: ModuleType) -> None:
    """Try a new pid"""
    data = _etf_bytes(
        [
            131,
            88,
            100,
            0,
            13,
            101,
            114,
            108,
            64,
            49,
            50,
            55,
            46,
            48,
            46,
            48,
            46,
            49,
            0,
            0,
            0,
            64,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
        ]
    )
    val, tail = codec.binary_to_term(data, None)
    assert isinstance(val, Pid)
    _assert_expected_tail(tail)


def test_decode_ref(codec: ModuleType) -> None:
    """Try a reference"""
    b1 = _etf_bytes(
        [
            131,
            114,
            0,
            3,
            100,
            0,
            13,
            101,
            114,
            108,
            64,
            49,
            50,
            55,
            46,
            48,
            46,
            48,
            46,
            49,
            1,
            0,
            0,
            1,
            58,
            0,
            0,
            0,
            2,
            0,
            0,
            0,
            0,
        ]
    )
    t1, tail = codec.binary_to_term(b1, None)
    assert isinstance(t1, Reference)
    _assert_expected_tail(tail)


def test_decode_newer_ref(codec: ModuleType) -> None:
    """Try a newer reference"""
    b1 = _etf_bytes(
        [
            131,
            90,
            0,
            3,
            100,
            0,
            13,
            101,
            114,
            108,
            64,
            49,
            50,
            55,
            46,
            48,
            46,
            48,
            46,
            49,
            0,
            0,
            0,
            1,
            0,
            0,
            1,
            58,
            0,
            0,
            0,
            2,
            0,
            0,
            0,
            0,
        ]
    )
    t1, tail = codec.binary_to_term(b1, None)
    assert isinstance(t1, Reference)
    _assert_expected_tail(tail)


def test_decode_tuple(codec: ModuleType) -> None:
    """Try decode some tuple values"""
    data1 = _etf_bytes(
        [
            131,
            py_impl.TAG_SMALL_TUPLE_EXT,
            2,
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_ATOM_EXT,
            0,
            2,
            111,
            107,
        ]
    )
    val1, tail1 = codec.binary_to_term(data1, None)
    assert (1, Atom("ok")) == val1
    _assert_expected_tail(tail1)

    data2 = _etf_bytes(
        [
            131,
            py_impl.TAG_LARGE_TUPLE_EXT,
            0,
            0,
            0,
            2,
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_ATOM_EXT,
            0,
            2,
            111,
            107,
        ]
    )
    val2, tail2 = codec.binary_to_term(data2, None)
    assert (1, Atom("ok")) == val2
    _assert_expected_tail(tail2)

    # Empty tuple
    data3 = _etf_bytes([131, py_impl.TAG_SMALL_TUPLE_EXT, 0])
    val3, tail3 = codec.binary_to_term(data3, None)
    assert () == val3
    _assert_expected_tail(tail3)


def test_decode_list(codec: ModuleType) -> None:
    """Try decode some list values"""
    data1 = _etf_bytes([131, py_impl.TAG_NIL_EXT])
    val1, tail1 = codec.binary_to_term(data1, None)
    assert [] == val1
    _assert_expected_tail(tail1)

    # Test data is [1, ok]
    data2 = _etf_bytes(
        [
            131,
            py_impl.TAG_LIST_EXT,
            0,
            0,
            0,
            2,
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_ATOM_EXT,
            0,
            2,
            111,
            107,
            py_impl.TAG_NIL_EXT,
        ]
    )
    val2, tail2 = codec.binary_to_term(data2, None)
    assert isinstance(val2, list), "Expected list, got: %s (%s)" % (
        val2.__class__.__name__,
        val2,
    )
    assert val2 == [1, Atom("ok")]
    _assert_expected_tail(tail2)


def test_decode_improper_list(codec: ModuleType) -> None:
    # Test data is [1 | ok]
    data3 = _etf_bytes(
        [
            131,
            py_impl.TAG_LIST_EXT,
            0,
            0,
            0,
            1,
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_ATOM_EXT,
            0,
            2,
            111,
            107,
        ]
    )
    val3, tail3 = codec.binary_to_term(data3, None)
    assert isinstance(val3, ImproperList), "Expected list, got: %s (%s)" % (
        val3.__class__.__name__,
        val3,
    )
    assert val3 == ImproperList([1], Atom("ok"))
    _assert_expected_tail(tail3)


def test_decode_map(codec: ModuleType) -> None:
    """Try a map #{1 => 2, ok => error}"""
    data = _etf_bytes(
        [
            131,
            py_impl.TAG_MAP_EXT,
            0,
            0,
            0,
            2,
            py_impl.TAG_SMALL_INT,
            1,
            py_impl.TAG_SMALL_INT,
            2,
            py_impl.TAG_ATOM_EXT,
            0,
            2,
            111,
            107,
            py_impl.TAG_ATOM_EXT,
            0,
            5,
            101,
            114,
            114,
            111,
            114,
        ]
    )
    val, tail = codec.binary_to_term(data, None)
    assert isinstance(val, dict)
    assert val == {1: 2, Atom("ok"): Atom("error")}
    _assert_expected_tail(tail)


def test_decode_float(codec: ModuleType) -> None:
    """Try decode a prepared double Pi"""
    data = _etf_bytes(
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
    negative = _etf_bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_NEW_FLOAT_EXT,
            192,
            71,
            188,
            40,
            245,
            194,
            143,
            92,
        ]
    )
    val, tail = codec.binary_to_term(data, None)
    nval, ntail = codec.binary_to_term(negative, None)
    assert val == 3.14159265358979
    _assert_expected_tail(tail)
    assert nval == -47.47
    _assert_expected_tail(ntail)


def test_decode_float_in_packed_type(codec: ModuleType) -> None:
    example = _etf_bytes(
        [
            py_impl.ETF_VERSION_TAG,
            py_impl.TAG_SMALL_TUPLE_EXT,
            3,
            py_impl.TAG_NEW_FLOAT_EXT,
            64,
            9,
            30,
            184,
            81,
            235,
            133,
            31,
            py_impl.TAG_SMALL_INT,
            13,
            py_impl.TAG_NEW_FLOAT_EXT,
            64,
            1,
            194,
            143,
            92,
            40,
            245,
            195,
        ]
    )
    val, tail = codec.binary_to_term(example, None)
    assert val == (3.14, 13, 2.22)
    _assert_expected_tail(tail)


def test_decode_int(codec: ModuleType) -> None:
    positive = _etf_bytes([131, 98, 0, 0, 18, 139])  # 4747
    negative = _etf_bytes([131, 98, 255, 255, 237, 117])  # -4747
    positive_val, positive_tail = codec.binary_to_term(positive, None)
    negative_val, negative_tail = codec.binary_to_term(negative, None)
    assert positive_val == 4747
    _assert_expected_tail(positive_tail)
    assert negative_val == -4747
    _assert_expected_tail(negative_tail)


def test_decode_small_big(codec: ModuleType) -> None:
    positive = _etf_bytes([131, 110, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # 2 ** 64
    negative = _etf_bytes([131, 110, 9, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1])  # - (2 ** 64)
    positive_val, positive_tail = codec.binary_to_term(positive, None)
    negative_val, negative_tail = codec.binary_to_term(negative, None)
    assert positive_val == 2**64
    _assert_expected_tail(positive_tail)
    assert negative_val == -(2**64)
    _assert_expected_tail(negative_tail)


def test_decode_small_big_random_bytes(codec: ModuleType) -> None:
    positive = _etf_bytes(
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
    negative = _etf_bytes(
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
    positive_val, positive_tail = codec.binary_to_term(positive, None)
    negative_val, negative_tail = codec.binary_to_term(negative, None)
    assert positive_val == 123456789012345678901234567890
    _assert_expected_tail(positive_tail)
    assert negative_val == -123456789012345678901234567890
    _assert_expected_tail(negative_tail)


def test_decode_large_big(codec: ModuleType) -> None:
    positive = _etf_bytes(
        [  # 2 ** 2040
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
    )
    negative = _etf_bytes(
        [  # - (2 ** 2040)
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
    )
    positive_val, positive_tail = codec.binary_to_term(positive, None)
    negative_val, negative_tail = codec.binary_to_term(negative, None)
    assert positive_val == 2**2040
    _assert_expected_tail(positive_tail)
    assert negative_val == -(2**2040)
    _assert_expected_tail(negative_tail)


def test_decode_binary(codec: ModuleType) -> None:
    """Decode binary to term.Binary and to Python bytes and compare.
    Binary is <<34>>.
    """
    data1 = _etf_bytes([131, 109, 0, 0, 0, 1, 34])
    val1, tail1 = codec.binary_to_term(data1, None)
    assert val1 == b'"'
    _assert_expected_tail(tail1)


def test_decode_hook(codec: ModuleType) -> None:
    def negate_hook(x: int) -> int:
        return -x

    positive = _etf_bytes([131, 98, 0, 0, 18, 139])  # 4747
    negative_val, tail = codec.binary_to_term(
        positive, {"decode_hook": {"int": negate_hook}}
    )
    assert negative_val == -4747
    _assert_expected_tail(tail)


def test_decode_bitstring_edges(codec: ModuleType) -> None:
    """What OTP 29's binary_to_term makes of these (TERM-20): 8 bits in the
    last byte is the binary <<5>>; unused low bits are cleared: <<1:1>>."""
    whole = bytes([131, 77, 0, 0, 0, 1, 8, 5])
    assert codec.binary_to_term(whole, {"bitstring": "BitString"}) == (b"\x05", b"")
    assert codec.binary_to_term(whole, None) == (b"\x05", b"")
    dirty = bytes([131, 77, 0, 0, 0, 1, 1, 255])
    value, _tail = codec.binary_to_term(dirty, {"bitstring": "BitString"})
    assert value == BitString(b"\x80", 1)
    assert codec.binary_to_term(dirty, None) == ((b"\x80", 1), b"")
    with pytest.raises(codec.PyCodecError):
        codec.binary_to_term(dirty, {"bitstring": "bits"})


# {a, [b, #{c => "d"}]} as term_to_binary writes it on OTP 29 (TERM-06).
NESTED = bytes(
    [131, 104, 2, 119, 1, 97, 108, 0, 0, 0, 2, 119, 1, 98, 116, 0, 0, 0, 1]
    + [119, 1, 99, 107, 0, 1, 100, 106]
)


def _typed(value: Any) -> Any:
    """``value`` with the exact type of every part spelled out, so that
    ``==`` also compares types (``Atom("a") == "a"`` otherwise)."""
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, [_typed(v) for v in value])
    if isinstance(value, dict):
        return ("dict", [(_typed(k), _typed(v)) for k, v in value.items()])
    return (type(value).__name__, value)


def _hooked(text: str) -> tuple[str, str]:
    return ("hooked", text)


# Options -> the value of NESTED decoded with them: every option and hook
# reaches the nested terms, not only the outermost one.
NESTED_CASES: dict[str, tuple[dict[str, Any], Any]] = {
    "atom_Atom": (
        {"atom": "Atom"},
        (Atom("a"), [Atom("b"), {Atom("c"): "d"}]),
    ),
    "atom_StrictAtom": (
        {"atom": "StrictAtom"},
        (StrictAtom("a"), [StrictAtom("b"), {StrictAtom("c"): "d"}]),
    ),
    "atom_str": ({"atom": "str"}, ("a", ["b", {"c": "d"}])),
    "atom_bytes": ({"atom": "bytes"}, (b"a", [b"b", {b"c": "d"}])),
    "atom_call": (
        {"atom_call": _hooked},
        (_hooked("a"), [_hooked("b"), {_hooked("c"): "d"}]),
    ),
    "atom_call_beats_atom": (
        {"atom": "bytes", "atom_call": _hooked},
        (_hooked("a"), [_hooked("b"), {_hooked("c"): "d"}]),
    ),
    "byte_string_str": (
        {"byte_string": "str"},
        (Atom("a"), [Atom("b"), {Atom("c"): "d"}]),
    ),
    "byte_string_bytes": (
        {"byte_string": "bytes"},
        (Atom("a"), [Atom("b"), {Atom("c"): b"d"}]),
    ),
    "byte_string_int_list": (
        {"byte_string": "int_list"},
        (Atom("a"), [Atom("b"), {Atom("c"): [100]}]),
    ),
    "hook_Atom": (
        {"decode_hook": {"Atom": lambda a: _hooked(str(a))}},
        (_hooked("a"), [_hooked("b"), {_hooked("c"): "d"}]),
    ),
    "hook_tuple": (
        {"decode_hook": {"tuple": list}},
        [Atom("a"), [Atom("b"), {Atom("c"): "d"}]],
    ),
    "hook_str_deepest": (
        {"decode_hook": {"str": str.upper}},
        (Atom("a"), [Atom("b"), {Atom("c"): "D"}]),
    ),
}


@pytest.mark.parametrize("case", list(NESTED_CASES))
def test_options_reach_nested_terms(codec: ModuleType, case: str) -> None:
    options, expected = NESTED_CASES[case]
    value, tail = codec.binary_to_term(NESTED, options)
    assert tail == b""
    assert _typed(value) == _typed(expected)
    # The same without the 131 byte.
    value, tail = codec.binary_to_term_2(NESTED[1:], options)
    assert tail == b""
    assert _typed(value) == _typed(expected)


def test_hook_sees_each_value_once(codec: ModuleType) -> None:
    """A hook runs once per value, children before their parent; the NIL
    that ends a list is not a value."""
    seen: list[str] = []

    def log(value: Any) -> Any:
        seen.append(type(value).__name__)
        return value

    hooks = {name: log for name in ("Atom", "list", "dict", "str", "tuple")}
    codec.binary_to_term(NESTED, {"decode_hook": hooks})
    assert seen == ["Atom", "Atom", "Atom", "str", "dict", "list", "tuple"]


def test_node_names_ignore_options(codec: ModuleType) -> None:
    """Node names of pids and references are Atom whatever the options; no
    hook sees them."""
    pid = (FIXTURE_DIR / "pid_small.etf").read_bytes()
    ref = (FIXTURE_DIR / "ref_3_words.etf").read_bytes()

    def no_atoms(value: Any) -> Any:
        raise AssertionError("hook called for %r" % (value,))

    for data in (pid, ref):
        for options in (
            {"atom": "bytes"},
            {"atom": "str", "decode_hook": {"Atom": no_atoms, "str": no_atoms}},
            {"atom_call": no_atoms},
        ):
            value, _tail = codec.binary_to_term(data, options)
            assert type(value.node_name_) is Atom
            assert value.node_name_ == "fix@host"


# An exception type only the tests below raise.
class _HookFailed(Exception):
    pass


def _fail(value: Any) -> Any:
    raise _HookFailed("no %r" % (value,))


@pytest.mark.parametrize(
    "options",
    [{"decode_hook": {"str": _fail}}, {"atom_call": _fail}],
    ids=["decode_hook", "atom_call"],
)
def test_callable_raising(codec: ModuleType, options: dict[str, Any]) -> None:
    """A raising option callable gives PyCodecError; the user's exception is
    its ``__cause__`` (TERM-08)."""
    with pytest.raises(codec.PyCodecError) as info:
        codec.binary_to_term(NESTED, options)
    assert isinstance(info.value.__cause__, _HookFailed)


@pytest.mark.parametrize(
    "name, key_type", [("map_list_key", "list"), ("map_map_key", "dict")]
)
def test_unhashable_map_key(codec: ModuleType, name: str, key_type: str) -> None:
    """A map key Python cannot hash gives PyCodecError naming the key's type,
    with the dict's TypeError as ``__cause__`` (TERM-08)."""
    data = (FIXTURE_DIR / (name + ".etf")).read_bytes()
    with pytest.raises(codec.PyCodecError, match="key of type %s" % key_type) as info:
        codec.binary_to_term(data, None)
    assert isinstance(info.value.__cause__, TypeError)


def test_improper_list_falsy_tail(codec: ModuleType) -> None:
    """[1|0] and [1|undefined] as OTP 29 writes them keep their tails."""
    zero = bytes([131, 108, 0, 0, 0, 1, 97, 1, 97, 0])
    undefined = bytes([131, 108, 0, 0, 0, 1, 97, 1, 119, 9]) + b"undefined"
    for data, tail in ((zero, 0), (undefined, None)):
        value, rest = codec.binary_to_term(data, None)
        assert rest == b""
        assert isinstance(value, ImproperList)
        assert value == ImproperList([1], tail)
        assert codec.term_to_binary(value, None) == data


@pytest.mark.parametrize(
    "options",
    [
        {"atom": "Atoms"},
        {"byte_string": "list"},
        {"atom_call": "not callable"},
        {"decode_hook": [("int", abs)]},
    ],
    ids=["atom", "byte_string", "atom_call", "decode_hook"],
)
def test_bad_options(codec: ModuleType, options: dict[str, Any]) -> None:
    with pytest.raises(codec.PyCodecError):
        codec.binary_to_term(NESTED, options)


def test_decode_fun(codec: ModuleType) -> None:
    data = _etf_bytes(
        [
            131,
            112,
            0,
            0,
            0,
            72,
            0,
            37,
            73,
            174,
            126,
            251,
            115,
            143,
            183,
            98,
            224,
            72,
            249,
            253,
            111,
            254,
            159,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            100,
            0,
            5,
            116,
            101,
            115,
            116,
            49,
            97,
            0,
            98,
            1,
            42,
            77,
            115,
            103,
            100,
            0,
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
            58,
            0,
            0,
            0,
            0,
            0,
            97,
            123,
        ]
    )
    val, tail = codec.binary_to_term(data, None)
    assert isinstance(val, Fun)
    _assert_expected_tail(tail)


def test_decode_compressed(codec: ModuleType) -> None:
    """tries to decode compressed data"""
    compressed_data = b"\x83P\x00\x00\x01\xc4x\x9c5\x90QR\x831\x08\x84\xebM\xf6\x00\x9d\x9eB\xdf|\xf5\x00\x98\xd0\xcaL\x08i\x02\x9d\xde\xce\xabI\xfc\xf5-\x04Xv?=\x9d^\xbe\xdfm\xb2B\xc6\nE\xb5f\x13K\x1c\xa4\xecg\x14\xeb\x8b\x8b\xb3\xc7\x04U\x19\xb2\xa4H\xbf\x81\x9bdwq\xcd\r\xb0\xc4R\xabp\xd6\x91\xdb\xd2\x8bT\xa9\xd1\x1d\xe1h\xf4\x99\xfa`?\xb4\x19J\xb7N\xa0&\xf7\xa0\x0b>\x1c\xdcES\x1c*\xfb\xf1\xc8\x92\xf4\x8c{\xc8B\xb7\xe53*\xf8\xc9\xb3\x88\x93\x8buDk\xa4\xc5\x0e\xe5=\x94\xa6\xf6\xa5_I\x199\x0c\xa6t\xae\xe9\xc9\x8e\x04y\xca/x\xdd\x92\x14\xce\x90\x19\xe9\xe4\x08+\x1d\x93\xc7\xe4/\xee\x95g&\xcf\x8f\x87\xb5\x18y\x8e\xd3N&\x05\xaf\xc5(\xd2\xda?\xa2\x0c\x14\xb8\xc6M\xc8\xd1\xb7!\x0c\x9aY\xc4\xbc\xe0\xedYx8\xc7\xe6\x98\x0c\xac\x14\xe2\x92s%\x86T\xf2\xbd\x91)\xc64\xa9\xdc7\xc5M*\x8f\x96h\x83vn\xd8\xf5\x9a\x98\t\x95\x17\xcf\xddUk\xdb\x06m@\x928\xd6\x1f\xd7\xd0\x0b~\x00"
    decoded_data = b"Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. "
    val, tail = codec.binary_to_term(compressed_data, None)
    assert val == decoded_data
    assert tail == b""


def test_decode_hook_compressed(codec: ModuleType) -> None:
    """tries to decode a compressed string, and convert it to unicode using
    a decode_hook.
    """

    def unicode_hook(x: bytes) -> str:
        return x.decode()

    compressed_data = b"\x83P\x00\x00\x01\xc4x\x9c5\x90QR\x831\x08\x84\xebM\xf6\x00\x9d\x9eB\xdf|\xf5\x00\x98\xd0\xcaL\x08i\x02\x9d\xde\xce\xabI\xfc\xf5-\x04Xv?=\x9d^\xbe\xdfm\xb2B\xc6\nE\xb5f\x13K\x1c\xa4\xecg\x14\xeb\x8b\x8b\xb3\xc7\x04U\x19\xb2\xa4H\xbf\x81\x9bdwq\xcd\r\xb0\xc4R\xabp\xd6\x91\xdb\xd2\x8bT\xa9\xd1\x1d\xe1h\xf4\x99\xfa`?\xb4\x19J\xb7N\xa0&\xf7\xa0\x0b>\x1c\xdcES\x1c*\xfb\xf1\xc8\x92\xf4\x8c{\xc8B\xb7\xe53*\xf8\xc9\xb3\x88\x93\x8buDk\xa4\xc5\x0e\xe5=\x94\xa6\xf6\xa5_I\x199\x0c\xa6t\xae\xe9\xc9\x8e\x04y\xca/x\xdd\x92\x14\xce\x90\x19\xe9\xe4\x08+\x1d\x93\xc7\xe4/\xee\x95g&\xcf\x8f\x87\xb5\x18y\x8e\xd3N&\x05\xaf\xc5(\xd2\xda?\xa2\x0c\x14\xb8\xc6M\xc8\xd1\xb7!\x0c\x9aY\xc4\xbc\xe0\xedYx8\xc7\xe6\x98\x0c\xac\x14\xe2\x92s%\x86T\xf2\xbd\x91)\xc64\xa9\xdc7\xc5M*\x8f\x96h\x83vn\xd8\xf5\x9a\x98\t\x95\x17\xcf\xddUk\xdb\x06m@\x928\xd6\x1f\xd7\xd0\x0b~\x00"
    decoded_data = "Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. "

    val, tail = codec.binary_to_term(
        compressed_data, {"decode_hook": {"bytes": unicode_hook}}
    )
    assert isinstance(val, str)
    assert val == decoded_data
    assert tail == b""


def test_decode_special(codec: ModuleType) -> None:
    """Test decoding true, false, undefined=None"""
    data1 = _etf_bytes(
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 4]) + b"true"
    )
    val1, tail1 = codec.binary_to_term(data1, None)
    assert val1 == True
    _assert_expected_tail(tail1)

    data2 = _etf_bytes(
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 5]) + b"false"
    )
    val2, tail2 = codec.binary_to_term(data2, None)
    assert val2 == False
    _assert_expected_tail(tail2)

    data3 = _etf_bytes(
        bytes([py_impl.ETF_VERSION_TAG, py_impl.TAG_SMALL_ATOM_UTF8_EXT, 9])
        + b"undefined"
    )
    val3, tail3 = codec.binary_to_term(data3, None)
    assert val3 == None
    _assert_expected_tail(tail3)
