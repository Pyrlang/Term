"""Tests of the native codec module alone; skipped when it is not built."""

from types import ModuleType

import pytest

import term.py_codec_impl as pycodec
from term.atom import Atom


def test_simple_b2t_errors(native_codec: ModuleType) -> None:
    with pytest.raises(BaseException):
        native_codec.binary_to_term(b"xxx", None)
        # Empty term creates empty input error
        native_codec.binary_to_term(b"", None)


def test_b2t_read_errors(native_codec: ModuleType) -> None:
    with pytest.raises(BaseException):
        # Compressed term (131, 80) with incomplete length field
        # should create read error
        native_codec.binary_to_term(b"\x83\x50\x00", None)


def test_b2t_library_equality_atoms(native_codec: ModuleType) -> None:
    a = pycodec.term_to_binary(Atom("hello"))
    b, _ = native_codec.binary_to_term(a, None)
    assert Atom("hello") == b
