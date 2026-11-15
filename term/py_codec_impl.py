# Copyright 2018, Erlang Solutions Ltd, and S2HC Sweden AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Module implements encoder and decoder from ETF (Erlang External Term Format)
used by the network distribution layer.
"""

import itertools
import math
import struct
from collections.abc import Iterator
from typing import Any, Callable, NoReturn, Optional, Union
from zlib import decompressobj
from zlib import error as zlib_error

from term import util
from term.atom import Atom, StrictAtom
from term.basetypes import Term
from term.bitstring import BitString
from term.fun import Export, Fun
from term.list import ImproperList
from term.pid import Pid
from term.port import Port
from term.reference import Reference

ETF_VERSION_TAG = 131

TAG_ATOM_EXT = 100
TAG_ATOM_UTF8_EXT = 118

TAG_BINARY_EXT = 109
TAG_BIT_BINARY_EXT = 77

TAG_COMPRESSED = 80

TAG_EXPORT_EXT = 113

TAG_FLOAT_EXT = 99

TAG_INT = 98

TAG_LARGE_BIG_EXT = 111
TAG_LARGE_TUPLE_EXT = 105
TAG_LIST_EXT = 108

TAG_MAP_EXT = 116

TAG_NEW_FLOAT_EXT = 70
TAG_NEW_FUN_EXT = 112
TAG_NEW_REF_EXT = 114
TAG_NIL_EXT = 106

TAG_PID_EXT = 103
TAG_PORT_EXT = 102
TAG_REFERENCE_EXT = 101

TAG_SMALL_ATOM_EXT = 115
TAG_SMALL_ATOM_UTF8_EXT = 119
TAG_SMALL_BIG_EXT = 110
TAG_SMALL_INT = 97
TAG_SMALL_TUPLE_EXT = 104
TAG_STRING_EXT = 107

TAG_NEW_PID_EXT = 88
TAG_NEW_PORT_EXT = 89
TAG_NEWER_REF_EXT = 90
TAG_V4_PORT_EXT = 120

# Largest creation of the old tags with an 8-bit creation (PID_EXT,
# PORT_EXT, REFERENCE_EXT, NEW_REFERENCE_EXT): ERTS_MAX_TINY_CREATION.
_MAX_TINY_CREATION = 3

# Most ID words in a reference (ERTS_MAX_REF_NUMBERS, OTP 24+).
_MAX_REF_WORDS = 5

# The first ID word of REFERENCE_EXT and NEW_REFERENCE_EXT is below this
# (MAX_REFERENCE: 18 bits).
_MAX_OLD_REF_FIRST_WORD = 1 << 18

# Hooks take and return arbitrary user values, hence Any.
EncodeHookType = Optional[dict[str, Callable[[Any], Any]]]

# Codec options are a dict of heterogeneous values (strings, callables, hook
# tables) supplied by the caller.
OptionsType = Optional[dict[str, Any]]


# This is Python variant of codec exception when Python impl is used.
# Otherwise native lib defines its own exception with same name.
# To use this, import via codec.py
class PyCodecError(Exception):
    pass


def incomplete_data(where: str = "") -> NoReturn:
    """This is called from many places to report incomplete data while
    decoding.
    """
    if where:
        raise PyCodecError("Incomplete data at " + where)
    else:
        raise PyCodecError("Incomplete data")


def binary_to_term(data: bytes, options: OptionsType = None) -> tuple[Term, bytes]:
    """Strip 131 header and unpack if the data was compressed.

    :param data: The incoming encoded data with the 131 byte
    :param options: as for :py:func:`binary_to_term_2`
    :raises PyCodecError: when the tag is not 131, when compressed
        data is incomplete or corrupted, on any malformed input, and when
        an option callable raises (the original is its ``__cause__``)
    :returns: The value and the remaining unconsumed bytes
    """
    dec = _Decoder(options)
    reader = _Reader(data)
    if reader.u8() != ETF_VERSION_TAG:
        raise PyCodecError("Unsupported external term version")

    if reader.peek() == TAG_COMPRESSED:
        reader.u8()
        reader = _Reader(_inflate(reader.u32(), reader.rest(), dec.max_size_))

    value = dec.decode(reader)
    return value, reader.rest()


def _inflate(declared: int, compressed: bytes, max_size: int) -> bytes:
    """The data of a compressed term: exactly ``declared`` bytes and a
    complete zlib stream. Inflates at most ``declared + 1`` bytes, so a
    stream that holds more fails without producing it."""
    if declared > max_size:
        raise PyCodecError(
            "Compressed term declares %d bytes, more than max_size %d"
            % (declared, max_size)
        )
    do = decompressobj()
    try:
        data = do.decompress(compressed, declared + 1)
    except zlib_error as e:
        raise PyCodecError("Compressed term: %s" % e) from e
    if len(data) > declared:
        raise PyCodecError(
            "Compressed term holds more than the declared %d bytes" % declared
        )
    if not do.eof:
        raise PyCodecError("Compressed term: the zlib stream is incomplete")
    if len(data) != declared:
        raise PyCodecError(
            "Compressed term holds %d bytes, declared %d" % (len(data), declared)
        )
    return data


# Big-endian fixed-size fields of the external term format.
_U16 = struct.Struct(">H")
_U32 = struct.Struct(">I")
_U64 = struct.Struct(">Q")
_I32 = struct.Struct(">i")
_F64 = struct.Struct(">d")


# A cursor over the input, as reader.rs in the native codec: every read is
# checked against the bytes that remain, so malformed input raises
# PyCodecError, never IndexError or struct.error.
class _Reader:
    __slots__ = ("data_", "pos_")

    def __init__(self, data: bytes) -> None:
        self.data_ = data
        self.pos_ = 0

    def remaining(self) -> int:
        return len(self.data_) - self.pos_

    def _need(self, n: int) -> int:
        """Claim ``n`` bytes; return where they start."""
        start = self.pos_
        if n > len(self.data_) - start:
            raise PyCodecError(
                "Incomplete data: %d bytes needed at offset %d, %d left"
                % (n, start, len(self.data_) - start)
            )
        self.pos_ = start + n
        return start

    def read(self, n: int) -> bytes:
        start = self._need(n)
        return self.data_[start : start + n]

    def peek(self) -> int:
        if self.pos_ >= len(self.data_):
            incomplete_data("offset %d" % self.pos_)
        return self.data_[self.pos_]

    def u8(self) -> int:
        return self.data_[self._need(1)]

    def u16(self) -> int:
        value: int = _U16.unpack_from(self.data_, self._need(2))[0]
        return value

    def u32(self) -> int:
        value: int = _U32.unpack_from(self.data_, self._need(4))[0]
        return value

    def u64(self) -> int:
        value: int = _U64.unpack_from(self.data_, self._need(8))[0]
        return value

    def i32(self) -> int:
        value: int = _I32.unpack_from(self.data_, self._need(4))[0]
        return value

    def f64(self) -> float:
        value: float = _F64.unpack_from(self.data_, self._need(8))[0]
        return value

    def rest(self) -> bytes:
        """The unread bytes; the reader is at the end afterwards."""
        start = self.pos_
        self.pos_ = len(self.data_)
        return self.data_[start:]


def _atom_text(name: bytes, tag: int) -> str:
    """The text of an atom: tags 100 and 115 carry Latin-1, 118 and 119 UTF-8."""
    if tag in (TAG_ATOM_EXT, TAG_SMALL_ATOM_EXT):
        return name.decode("latin-1")
    try:
        return name.decode("utf8")
    except UnicodeDecodeError as e:
        raise PyCodecError("Atom is not valid UTF-8: %s" % e) from e


def _read_atom_text(reader: _Reader, tag: int) -> str:
    """The length and text of an atom whose tag was just read."""
    size = reader.u16() if tag in (TAG_ATOM_EXT, TAG_ATOM_UTF8_EXT) else reader.u8()
    return _atom_text(reader.read(size), tag)


# Tags that carry an atom.
_ATOM_TAGS = (
    TAG_ATOM_EXT,
    TAG_ATOM_UTF8_EXT,
    TAG_SMALL_ATOM_EXT,
    TAG_SMALL_ATOM_UTF8_EXT,
)


def _get_create_atom_fn(
    opt: object, create_fn: Optional[Callable[[str], Any]]
) -> Callable[[str], Any]:
    """The function that turns atom text into the value the options ask for."""
    if create_fn is not None:
        return create_fn
    if opt == "Atom":
        return Atom
    elif opt == "StrictAtom":
        return StrictAtom
    elif opt == "str":
        return str
    elif opt == "bytes":
        # The UTF-8 text, whichever tag carried the atom (as the native codec).
        return lambda text: text.encode("utf8")

    raise PyCodecError(
        "Option 'atom' is %r; expected 'str', 'bytes', 'Atom', 'StrictAtom'" % (opt,)
    )


def _get_create_str_fn(opt: object) -> Callable[[bytes], Union[str, bytes, list[int]]]:
    """A tool function to create either a str or bytes from a 8-bit string."""

    def _create_int_list(name: bytes) -> list[int]:
        return list(name)

    def _create_str_bytes(name: bytes) -> bytes:
        return name

    def _create_str_str(name: bytes) -> str:
        return name.decode("latin-1")

    if opt == "str":
        return _create_str_str
    elif opt == "bytes":
        return _create_str_bytes
    elif opt == "int_list":
        return _create_int_list

    raise PyCodecError(
        "Option 'byte_string' is %r; expected 'str', 'bytes', 'int_list'" % (opt,)
    )


# Default of option "max_depth": how deeply terms may nest.
DEFAULT_MAX_DEPTH = 4096

# Default of option "max_size": the largest size, in bytes, that a compressed
# term may declare for its data (256 MiB).
DEFAULT_MAX_SIZE = 256 * 1024 * 1024


def _positive_int_option(options: dict[str, Any], name: str, default: int) -> int:
    value = options.get(name, default)
    if type(value) is not int or value < 1:
        raise PyCodecError("Option %r is %r; expected a positive int" % (name, value))
    return value


def _user_error(e: Exception) -> PyCodecError:
    """A PyCodecError for an exception raised by an option callable; the
    caller raises it ``from e`` so the original stays reachable."""
    return PyCodecError("%s: %s" % (type(e).__name__, e))


# The decoding options, resolved once per call and shared by every nested
# term, so that options and hooks apply at every depth (as in the native codec).
class _Decoder:
    def __init__(self, options: OptionsType) -> None:
        if options is None:
            options = {}
        atom_call = options.get("atom_call")
        if atom_call is not None and not callable(atom_call):
            raise PyCodecError("Option 'atom_call' must be callable")
        self.create_atom_: Callable[[str], Any] = _get_create_atom_fn(
            options.get("atom", "Atom"), atom_call
        )
        self.create_str_ = _get_create_str_fn(options.get("byte_string", "str"))
        hooks = options.get("decode_hook")
        if hooks is not None and not isinstance(hooks, dict):
            raise PyCodecError("Option 'decode_hook' must be a dict")
        # Hook functions are user code taking and returning any value.
        self.decode_hook_: dict[str, Callable[[Any], Any]] = hooks or {}
        bitstring = options.get("bitstring", "tuple")
        if bitstring not in ("tuple", "BitString"):
            raise PyCodecError(
                "Option 'bitstring' is %r; expected 'tuple', 'BitString'" % (bitstring,)
            )
        self.bitstring_as_tuple_ = bitstring == "tuple"
        self.max_depth_ = _positive_int_option(options, "max_depth", DEFAULT_MAX_DEPTH)
        self.max_size_ = _positive_int_option(options, "max_size", DEFAULT_MAX_SIZE)

    def bitstring(self, value: bytes, bits: int) -> Any:
        """A bitstring as the options ask: ``(bytes, bits)`` or ``BitString``."""
        if self.bitstring_as_tuple_:
            return (value, bits)
        return BitString(value, bits)

    def atom(self, text: str) -> Any:
        """An atom as the options ask; true, false, undefined become Python
        True, False, None whatever the options say."""
        if text == "true":
            return True
        elif text == "false":
            return False
        elif text == "undefined":
            return None
        try:
            return self.create_atom_(text)
        except Exception as e:  # user code (atom_call) may raise anything
            raise _user_error(e) from e

    def hook(self, value: Any) -> Any:
        """``value`` passed through the decode hook of its type, if any."""
        if self.decode_hook_:
            hook = self.decode_hook_.get(type(value).__name__)
            if hook is not None:
                try:
                    return hook(value)
                except Exception as e:  # user code may raise anything
                    raise _user_error(e) from e
        return value

    def decode(self, reader: _Reader) -> Any:
        """Decode one term; every value in it, the term itself included,
        passes through the decode hook of its type, children first.

        Iterative: compound terms wait on an explicit stack of ``_Frame``,
        at most ``max_depth`` of them, so neither Python's recursion limit
        nor the C stack bounds the nesting (as in the native codec).
        """
        stack: list[_Frame] = []
        while True:
            value = _start_term(self, reader)
            hooked = False
            if isinstance(value, _Frame):
                value, hooked = value.open(reader)
                if isinstance(value, _Frame):
                    if len(stack) >= self.max_depth_:
                        raise PyCodecError(
                            "Term is nested deeper than max_depth %d" % self.max_depth_
                        )
                    stack.append(value)
                    continue
            # Pass finished values up to the frames waiting for them.
            while True:
                if not hooked:
                    value = self.hook(value)
                if not stack:
                    return value
                frame = stack[-1]
                value, hooked = frame.add(self, value, reader)
                if value is frame:
                    break  # the frame needs more children
                stack.pop()


def _decode_plain_atom(reader: _Reader, what: str) -> Atom:
    """An atom that is part of another term (``what``): always an ``Atom``,
    ``true`` and ``false`` too, whatever the options and hooks say."""
    tag = reader.u8()
    if tag not in _ATOM_TAGS:
        raise PyCodecError("%s must be an atom, found tag %d" % (what, tag))
    return Atom(_read_atom_text(reader, tag))


def _decode_node(reader: _Reader) -> Atom:
    """The node name of a pid, port or reference."""
    return _decode_plain_atom(reader, "Node name")


# Range of a small integer on a 64-bit OTP emulator (MIN_SMALL, MAX_SMALL):
# what OTP accepts for the integer fields of EXPORT_EXT and NEW_FUN_EXT.
_MIN_SMALL = -(2**59)
_MAX_SMALL = 2**59 - 1


def _decode_small_int(reader: _Reader, what: str) -> int:
    """An integer field of another term (``what``) that OTP decodes as a
    whole term and requires to be small: any integer encoding is accepted."""
    tag = reader.u8()
    if tag == TAG_SMALL_INT:
        return reader.u8()
    if tag == TAG_INT:
        return reader.i32()
    if tag in (TAG_SMALL_BIG_EXT, TAG_LARGE_BIG_EXT):
        nbytes = reader.u8() if tag == TAG_SMALL_BIG_EXT else reader.u32()
        sign = reader.u8()
        value = int.from_bytes(reader.read(nbytes), "little")
        if sign:
            value = -value
        if not _MIN_SMALL <= value <= _MAX_SMALL:
            raise PyCodecError("%s is out of range" % what)
        return value
    raise PyCodecError("%s must be an integer, found tag %d" % (what, tag))


def _decode_export_arity(reader: _Reader) -> int:
    """The Arity of ``EXPORT_EXT``: a non-negative small integer (OTP 29
    accepts INTEGER_EXT and bignums too)."""
    arity: int = _decode_small_int(reader, "EXPORT_EXT arity")
    if arity < 0:
        raise PyCodecError("EXPORT_EXT arity is out of range")
    return arity


def _decode_pid(reader: _Reader, tag: int) -> Pid:
    """The rest of a ``PID_EXT`` or ``NEW_PID_EXT`` whose tag was read. ID
    and Serial are not limited for a remote node (OTP 29's dec_pid checks
    them only for its own pids); the 8-bit Creation is."""
    node = _decode_node(reader)
    id1 = reader.u32()
    serial = reader.u32()
    if tag == TAG_PID_EXT:
        creation = _tiny_creation(reader, "PID_EXT")
    else:
        creation = reader.u32()
    return Pid(node_name=node, id=id1, serial=serial, creation=creation)


# Most free variables of a fun (MAX_ARG in OTP).
_MAX_FUN_FREE = 255


def _start_fun(reader: _Reader) -> Any:
    """``NEW_FUN_EXT`` after its tag: the header and the four fixed parts
    are read here, as OTP checks them (Module an atom, OldIndex and OldUniq
    small integers, a creator pid); the free variables follow as children."""
    reader.u32()  # Size: OTP ignores it too (TERM-05)
    arity = reader.u8()
    uniq = reader.read(16)
    index = reader.u32()
    num_free = reader.u32()
    if num_free > _MAX_FUN_FREE:
        raise PyCodecError("NEW_FUN_EXT has %d free variables, at most 255" % num_free)
    _count(reader, num_free, 1, "NEW_FUN_EXT")
    module = _decode_plain_atom(reader, "NEW_FUN_EXT module")
    old_index = _decode_small_int(reader, "NEW_FUN_EXT OldIndex")
    old_uniq = _decode_small_int(reader, "NEW_FUN_EXT OldUniq")
    tag = reader.u8()
    if tag not in (TAG_PID_EXT, TAG_NEW_PID_EXT):
        raise PyCodecError("NEW_FUN_EXT pid must be a pid, found tag %d" % tag)
    pid = _decode_pid(reader, tag)
    fun = Fun(
        mod=module,
        arity=arity,
        pid=pid,
        index=index,
        uniq=uniq,
        old_index=old_index,
        old_uniq=old_uniq,
        free=[],
    )
    return _Frame(_FUN, num_free, fun.free_, fun)


def binary_to_term_2(data: bytes, options: OptionsType = None) -> tuple[Term, bytes]:
    """Proceed decoding after leading tag has been checked and removed.

    Erlang lists are decoded into ``term.List`` object, whose ``elements_``
    field contains the data, ``tail_`` field has the optional tail and a
    helper function exists to assist with extracting an unicode string.

    Atoms are decoded to :py:class:`~Term.atom.Atom` or optionally to bytes
    or to strings. If `atom_call` is provided that will be called and the
    returned value will be used as representation if atoms
    Pids are decoded into :py:class:`~Term.pid.Pid`.
    Refs decoded to and :py:class:`~Term.reference.Reference`.
    Maps are decoded into Python ``dict``.
    Binaries are decoded into ``bytes``
    object and bitstrings into a pair of ``(bytes, last_byte_bits:int)``
    or a ``BitString`` (option "bitstring").

    :param options: dict(str, _);
            * "atom": "str" | "bytes" | "Atom" | "StrictAtom"; default "Atom".
              Returns atoms as strings, as bytes or as atom.Atom class objects
            * "atom_call": callable object that will get str as input the
              returned value will be used as atom representation; takes
              precedence over "atom"
            * "byte_string": "str" | "bytes" | "int_list" (default "str").
              Returns 8-bit strings as Python str or bytes or int list.
            * "bitstring": "tuple" | "BitString" (default "tuple"). Returns
              bitstrings as ``(bytes, last_byte_bits)`` or as
              :py:class:`~term.bitstring.BitString`, which encodes back to a
              bitstring.
            * "decode_hook": dict of type name -> callable, called for every
              decoded value (nested ones too) whose type has that name.
              Options and hooks apply at every nesting level; node names of
              pids and references are always ``Atom``.
    :param data: Bytes containing encoded term without 131 header
    :rtype: Tuple[Value, Tail: bytes]
    :return: The function consumes as much data as
        possible and returns the tail. Tail can be used again to parse
        another term if there was any.
    :raises PyCodecError(str): on malformed input, and when an option
        callable raises (the original exception is its ``__cause__``)
    """
    dec = _Decoder(options)
    reader = _Reader(data)
    value = dec.decode(reader)
    return value, reader.rest()


# Kinds of _Frame: the compound term being decoded.
_LIST = 0  # LIST_EXT elements
_LIST_TAIL = 1  # LIST_EXT tail that is not NIL
_TUPLE = 2
_MAP = 3  # keys and values in turn
_FUN = 4  # NEW_FUN_EXT free variables

# _Frame.key_ while a map waits for a key, not a value.
_NO_KEY: Any = object()


# A compound term whose children are being decoded (see _Decoder.decode).
class _Frame:
    __slots__ = ("kind_", "items_", "remaining_", "key_", "fun_")

    def __init__(
        self,
        kind: int,
        remaining: int,
        items: Any,
        fun: Optional[Fun] = None,
    ) -> None:
        self.kind_ = kind
        self.remaining_ = remaining  # children still to come
        self.items_ = items  # list of children; a dict for a map
        self.key_: Any = _NO_KEY
        self.fun_ = fun  # the fun whose free variables (items_) these are

    def open(self, reader: _Reader) -> tuple[Any, bool]:
        """Just started: itself if children follow, else ``(value, hooked)``."""
        if self.remaining_:
            return self, False
        if self.kind_ == _LIST:
            return self._list_end(reader)
        if self.kind_ == _TUPLE:
            return (), False
        if self.kind_ == _FUN:
            return self.fun_, False
        return self.items_, False  # an empty map

    def _list_end(self, reader: _Reader) -> tuple[Any, bool]:
        # A NIL tail makes a proper list; it is not a value of its own, so
        # no decode hook sees it. Any other tail is decoded next.
        if reader.peek() == TAG_NIL_EXT:
            reader.u8()
            return self.items_, False
        self.kind_ = _LIST_TAIL
        return self, False

    def add(self, dec: "_Decoder", value: Any, reader: _Reader) -> tuple[Any, bool]:
        """Take the next child: itself while more follow, else the finished
        term as ``(value, hooked)``."""
        kind = self.kind_
        if kind == _MAP:
            if self.key_ is _NO_KEY:
                self.key_ = value
                return self, False
            key = self.key_
            self.key_ = _NO_KEY
            try:
                self.items_[key] = value
            except TypeError as e:
                raise PyCodecError(
                    "Map key of type %s is not hashable" % type(key).__name__
                ) from e
            self.remaining_ -= 1
            return (self, False) if self.remaining_ else (self.items_, False)
        if kind == _LIST_TAIL:
            if not self.items_:
                # A zero-length list is its tail, already hooked:
                # <<108,0,0,0,0,97,42>> is 42 (binary_SUITE:robustness).
                return value, True
            return ImproperList(self.items_, value), False
        self.items_.append(value)
        self.remaining_ -= 1
        if self.remaining_:
            return self, False
        if kind == _LIST:
            return self._list_end(reader)
        if kind == _TUPLE:
            return tuple(self.items_), False
        return self.fun_, False  # kind == _FUN; items_ is its free_ list


def _tiny_creation(reader: _Reader, what: str) -> int:
    """The 8-bit Creation of an old node-container tag: at most 3
    (``is_tiny_creation`` in OTP's external.c)."""
    creation = reader.u8()
    if creation > _MAX_TINY_CREATION:
        raise PyCodecError("%s creation %d is above 3" % (what, creation))
    return creation


def _ref_words(reader: _Reader, what: str) -> int:
    """The ID word count of a reference: 1 to 5 (``ERTS_MAX_REF_NUMBERS``).

    OTP 29 also decodes a ``NEWER_REFERENCE_EXT`` with no words, but only by
    reading its first word from beyond the term; we reject it."""
    words = reader.u16()
    if not 1 <= words <= _MAX_REF_WORDS:
        raise PyCodecError("%s has %d ID words, expected 1..5" % (what, words))
    return words


def _first_ref_word(refid: bytes, what: str) -> bytes:
    """``refid`` if its first word fits the 18 bits that the tags with an
    8-bit creation allow (``MAX_REFERENCE`` in OTP)."""
    if _U32.unpack_from(refid)[0] >= _MAX_OLD_REF_FIRST_WORD:
        raise PyCodecError("%s first ID word is above 18 bits" % what)
    return refid


def _count(reader: _Reader, count: int, per_element: int, what: str) -> int:
    """``count`` if the input can hold that many elements of at least
    ``per_element`` bytes each; checked before anything is allocated."""
    if count * per_element > reader.remaining():
        raise PyCodecError(
            "%s declares %d elements but only %d bytes remain"
            % (what, count, reader.remaining())
        )
    return count


def _start_term(dec: _Decoder, reader: _Reader) -> Any:
    """Read the next term: its value, or a ``_Frame`` for a compound term
    whose children follow."""
    tag = reader.u8()

    if tag in _ATOM_TAGS:
        return dec.atom(_read_atom_text(reader, tag))

    if tag == TAG_NIL_EXT:
        return []

    if tag == TAG_STRING_EXT:
        return dec.create_str_(reader.read(reader.u16()))

    if tag == TAG_LIST_EXT:
        # The elements and then the tail, at least one byte each.
        return _Frame(_LIST, _count(reader, reader.u32(), 1, "LIST_EXT"), [])

    if tag == TAG_SMALL_TUPLE_EXT:
        return _Frame(_TUPLE, _count(reader, reader.u8(), 1, "SMALL_TUPLE_EXT"), [])

    if tag == TAG_LARGE_TUPLE_EXT:
        return _Frame(_TUPLE, _count(reader, reader.u32(), 1, "LARGE_TUPLE_EXT"), [])

    if tag == TAG_MAP_EXT:
        pairs = _count(reader, reader.u32(), 2, "MAP_EXT")
        return _Frame(_MAP, pairs, {})

    if tag == TAG_SMALL_INT:
        return reader.u8()

    if tag == TAG_INT:
        return reader.i32()

    if tag in (TAG_PID_EXT, TAG_NEW_PID_EXT):
        return _decode_pid(reader, tag)

    if tag in (TAG_PORT_EXT, TAG_NEW_PORT_EXT, TAG_V4_PORT_EXT):
        node = _decode_node(reader)
        port_id = reader.u64() if tag == TAG_V4_PORT_EXT else reader.u32()
        if tag == TAG_PORT_EXT:
            creation = _tiny_creation(reader, "PORT_EXT")
        else:
            creation = reader.u32()
        return Port(node_name=node, id=port_id, creation=creation)

    if tag == TAG_REFERENCE_EXT:
        node = _decode_node(reader)
        refid = _first_ref_word(reader.read(4), "REFERENCE_EXT")
        creation = _tiny_creation(reader, "REFERENCE_EXT")
        return Reference(node_name=node, creation=creation, refid=refid)

    if tag == TAG_NEW_REF_EXT:
        words = _ref_words(reader, "NEW_REFERENCE_EXT")
        node = _decode_node(reader)
        creation = _tiny_creation(reader, "NEW_REFERENCE_EXT")
        refid = _first_ref_word(reader.read(4 * words), "NEW_REFERENCE_EXT")
        return Reference(node_name=node, creation=creation, refid=refid)

    if tag == TAG_NEWER_REF_EXT:
        words = _ref_words(reader, "NEWER_REFERENCE_EXT")
        node = _decode_node(reader)
        creation = reader.u32()
        return Reference(
            node_name=node, creation=creation, refid=reader.read(4 * words)
        )

    if tag == TAG_BINARY_EXT:
        # Returned as Python `bytes`
        return reader.read(reader.u32())

    if tag == TAG_BIT_BINARY_EXT:
        size = reader.u32()
        bits = reader.u8()
        _check_bits(size, bits)
        value = reader.read(size)
        if bits == 8:
            # A whole last byte: the term is a binary (as OTP decodes it).
            return value
        return dec.bitstring(_mask_last_byte(value, bits), bits)

    if tag == TAG_NEW_FLOAT_EXT:
        return reader.f64()

    if tag in (TAG_SMALL_BIG_EXT, TAG_LARGE_BIG_EXT):
        nbytes = reader.u8() if tag == TAG_SMALL_BIG_EXT else reader.u32()
        sign = reader.u8()
        # Data is encoded little-endian as bytes (least significant first)
        result = int.from_bytes(reader.read(nbytes), byteorder="little")
        return -result if sign != 0 else result

    if tag == TAG_EXPORT_EXT:
        module = _decode_plain_atom(reader, "EXPORT_EXT module")
        function = _decode_plain_atom(reader, "EXPORT_EXT function")
        return Export(module, function, _decode_export_arity(reader))

    if tag == TAG_NEW_FUN_EXT:
        return _start_fun(reader)

    raise PyCodecError("Unknown tag %d" % tag)


# Range of INTEGER_EXT: a signed 32-bit integer.
_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1

# Most magnitude bytes LARGE_BIG_EXT can declare.
_BIG_MAX_BYTES = 2**32 - 1


def _pack_int(val: int) -> bytes:
    """``SMALL_INTEGER_EXT`` for 0..255, ``INTEGER_EXT`` for signed 32 bits,
    otherwise a bignum: little-endian magnitude without leading zero bytes."""
    if 0 <= val < 256:
        return bytes([TAG_SMALL_INT, val])
    if _INT_MIN <= val <= _INT_MAX:
        return bytes([TAG_INT]) + util.to_i32(val)
    sign = 1 if val < 0 else 0
    magnitude = -val if sign else val
    size = (magnitude.bit_length() + 7) // 8
    if size < 256:
        hdr = bytes([TAG_SMALL_BIG_EXT, size, sign])
    elif size <= _BIG_MAX_BYTES:
        hdr = bytes([TAG_LARGE_BIG_EXT]) + util.to_u32(size) + bytes([sign])
    else:
        raise PyCodecError("Integer is too large for LARGE_BIG_EXT")
    return hdr + magnitude.to_bytes(size, "little")


# TODO: maybe move this into atom class
def _pack_atom(text: str) -> bytes:
    atom_bytes = bytes(text, "utf8")
    if len(atom_bytes) < 256:
        return bytes([TAG_SMALL_ATOM_UTF8_EXT, len(atom_bytes)]) + atom_bytes
    return bytes([TAG_ATOM_UTF8_EXT]) + util.to_u16(len(atom_bytes)) + atom_bytes


def _pack_pid(val: Pid) -> bytes:
    """``NEW_PID_EXT``: ID, Serial and Creation are 32 bits each."""
    try:
        fields = _PID_FIELDS.pack(val.id_, val.serial_, val.creation_)
    except struct.error as e:
        raise PyCodecError("Pid field out of range: %s" % e) from e
    return bytes([TAG_NEW_PID_EXT]) + _pack_atom(val.node_name_) + fields


# ID, Serial and Creation of NEW_PID_EXT.
_PID_FIELDS = struct.Struct(">III")


def _pack_export(val: Export) -> bytes:
    """``EXPORT_EXT``: Module, Function, then Arity as OTP writes integers."""
    if type(val.arity_) is not int or not 0 <= val.arity_ <= _MAX_SMALL:
        raise PyCodecError("EXPORT_EXT arity is out of range")
    return (
        bytes([TAG_EXPORT_EXT])
        + _pack_atom(val.module_)
        + _pack_atom(val.function_)
        + _pack_int(val.arity_)
    )


def _pack_port(val: Port) -> bytes:
    """Always ``V4_PORT_EXT``, as OTP 26+ writes every port."""
    if not (0 <= val.id_ < 2**64 and 0 <= val.creation_ < 2**32):
        raise PyCodecError(
            "Port id %r or creation %r out of range" % (val.id_, val.creation_)
        )
    return (
        bytes([TAG_V4_PORT_EXT])
        + _pack_atom(val.node_name_)
        + _U64.pack(val.id_)
        + _U32.pack(val.creation_)
    )


def _pack_ref(val: Reference) -> bytes:
    """``NEWER_REFERENCE_EXT`` with 1 to 5 ID words."""
    words, rest = divmod(len(val.id_), 4)
    if rest or not 1 <= words <= _MAX_REF_WORDS:
        raise PyCodecError(
            "Reference ID of %d bytes; expected 1..5 words of 4 bytes" % len(val.id_)
        )
    if not 0 <= val.creation_ < 2**32:
        raise PyCodecError("Reference creation %r out of range" % (val.creation_,))
    return (
        bytes([TAG_NEWER_REF_EXT])
        + util.to_u16(words)
        + _pack_atom(val.node_name_)
        + _U32.pack(val.creation_)
        + val.id_
    )


def _is_a_simple_object(obj: object) -> bool:
    """Check whether a value can be simply encoded by term_to_binary and
    does not require class unwrapping by `serialize_object`.
    """
    return (
        type(obj) == str
        or type(obj) == list
        or type(obj) == tuple
        or type(obj) == dict
        or type(obj) == int
        or type(obj) == float
        or isinstance(obj, Atom)
        or isinstance(obj, Pid)
        or isinstance(obj, Reference)
    )


def generic_serialize_object(
    obj: Any, cycle_detect: Optional[set[int]] = None
) -> tuple[Optional[tuple[bytes, dict[bytes, Any]]], set[int]]:
    """Given an arbitraty Python object creates a tuple (ClassName, {Fields}).
    A fair effort is made to avoid infinite recursion on cyclic objects.
    :param obj: Arbitrary object to encode
    :param cycle_detect: A set with ids of object, for cycle detection
    :return: A pair of result: (ClassName :: bytes(), Fields :: {bytes(), _})
        or None, and a CycleDetect value
    """
    if cycle_detect is None:
        cycle_detect = set()

    # if cyclic encoding detected, ignore this value
    if id(obj) in cycle_detect:
        return None, cycle_detect

    cycle_detect.add(id(obj))

    object_name = type(obj).__name__
    fields: dict[bytes, Any] = {}
    for key in obj.__dict__:
        val = getattr(obj, key)
        if not callable(val) and not key.startswith("_"):
            if _is_a_simple_object(val):
                fields[bytes(key, "latin1")] = val
            else:
                ser, cycle_detect = generic_serialize_object(
                    val, cycle_detect=cycle_detect
                )
                fields[bytes(key, "latin1")] = ser

    return (bytes(object_name, "latin1"), fields), cycle_detect


# Most characters STRING_EXT can hold (a 16-bit length).
_STRING_EXT_MAX = 65535


def _pack_str(val: str) -> bytes:
    """A string is a list of code points: ``STRING_EXT`` (one Latin-1 byte
    per character) when every code point is below 256 and there are at most
    65535 of them, else ``LIST_EXT`` of integers; ``""`` is ``NIL_EXT``."""
    if not val:
        return bytes([TAG_NIL_EXT])
    if len(val) <= _STRING_EXT_MAX:
        try:
            latin1 = val.encode("latin-1")
        except UnicodeEncodeError:
            pass
        else:
            return bytes([TAG_STRING_EXT]) + util.to_u16(len(latin1)) + latin1
    elements = b"".join(_pack_int(ord(ch)) for ch in val)
    return (
        bytes([TAG_LIST_EXT]) + util.to_u32(len(val)) + elements + bytes([TAG_NIL_EXT])
    )


def _pack_float(val: float) -> bytes:
    if not math.isfinite(val):
        raise PyCodecError("Float value %s is not finite" % val)
    return bytes([TAG_NEW_FLOAT_EXT]) + struct.pack(">d", val)


def _check_bits(size: int, bits: int) -> None:
    """``BIT_BINARY_EXT`` carries 1..8 bits in its last byte, so it has a
    last byte (binary_SUITE:bad_terms, bad_binary_to_term)."""
    if not 1 <= bits <= 8:
        raise PyCodecError("Bitstring: %d bits in the last byte, expected 1..8" % bits)
    if size == 0:
        raise PyCodecError("Bitstring: no bytes to hold %d bits" % bits)


def _mask_last_byte(value: bytes, bits: int) -> bytes:
    """Clear the unused low bits of the last byte, as OTP does."""
    last = value[-1] & (0xFF << (8 - bits)) & 0xFF
    return value[:-1] + bytes([last])


def _pack_binary(data: bytes, last_byte_bits: int) -> bytes:
    if last_byte_bits == 8:
        return bytes([TAG_BINARY_EXT]) + util.to_u32(len(data)) + data

    _check_bits(len(data), last_byte_bits)
    return (
        bytes([TAG_BIT_BINARY_EXT])
        + util.to_u32(len(data))
        + bytes([last_byte_bits])
        + _mask_last_byte(data, last_byte_bits)
    )


# A compound value whose children are being encoded (see _encode): the
# container (kept alive, and its id marks it open), the children still to
# come, and what to do after them: _END_NOTHING, _END_NIL (write NIL_EXT, a
# proper list) or, if 0 or more, the offset of a NEW_FUN_EXT Size to fill in.
_EncFrame = tuple[object, Iterator[Any], int]
_END_NOTHING = -1
_END_NIL = -2


def _substitute(val: Any, encode_hook: EncodeHookType) -> Any:
    """The value that stands for ``val``, which has no encoding of its own:
    what the "catch_all" hook or the ``__etf__`` method returns, else the
    ``(ClassName, Fields)`` tuple of ``generic_serialize_object``."""
    catch_all = None
    if encode_hook is not None:
        catch_all = encode_hook.get("catch_all", None)
    if catch_all is not None:
        return catch_all(val)
    etf = getattr(val, "__etf__", None)
    if etf is not None:
        return etf()
    try:
        ser, _ = generic_serialize_object(val)
    except RecursionError as e:
        raise PyCodecError(
            "Object %s nests too deeply to serialize" % type(val).__name__
        ) from e
    return ser


# Returned by _start_value: encode `value_` in place of the value given.
class _Substitute:
    __slots__ = ("value_",)

    def __init__(self, value: Any) -> None:
        self.value_ = value


def _start_value(
    val: Any, encode_hook: EncodeHookType, out: bytearray
) -> Union[None, _EncFrame, _Substitute]:
    """Write ``val`` to ``out``; or write the header of a compound value
    and return its frame, as its children follow; or return the value to
    encode in its place."""
    type_name_ref = type(val).__name__
    if encode_hook is not None and type_name_ref in encode_hook:
        hook_fn = encode_hook.get(type_name_ref)
        if hook_fn is not None:
            val = hook_fn(val)
        else:
            raise PyCodecError(
                f"term_to_binary: No hook function for type {type_name_ref}"
            )

    type_val = type(val)
    if type_val == int:
        out += _pack_int(val)
    elif type_val == float:
        out += _pack_float(val)
    elif type_val == str:
        out += _pack_str(val)
    elif type_val == bool:
        out += _pack_atom("true") if val else _pack_atom("false")
    elif type_val == list:
        if not val:
            out.append(TAG_NIL_EXT)  # `[]` is NIL_EXT alone, as OTP writes it
            return None
        out.append(TAG_LIST_EXT)
        out += util.to_u32(len(val))
        return (val, iter(val), _END_NIL)
    elif type_val == tuple:
        if len(val) < 256:
            out += bytes([TAG_SMALL_TUPLE_EXT, len(val)])
        else:
            out.append(TAG_LARGE_TUPLE_EXT)
            out += util.to_u32(len(val))
        return (val, iter(val), _END_NOTHING) if val else None
    elif type_val == dict:
        out.append(TAG_MAP_EXT)
        out += util.to_u32(len(val))
        if not val:
            return None
        # A snapshot of the pairs: a hook that changes the dict while it is
        # encoded cannot break the iteration (as in the native codec).
        pairs = list(val.items())
        return (val, (x for pair in pairs for x in pair), _END_NOTHING)
    elif val is None:
        out += _pack_atom("undefined")
    elif isinstance(val, Atom):
        out += _pack_atom(val)
    elif isinstance(val, ImproperList):
        if not val._elements:
            # `[... | T]` with no elements is `T` itself
            return _Substitute(val._tail)
        out.append(TAG_LIST_EXT)
        out += util.to_u32(len(val._elements))
        return (val, itertools.chain(val._elements, (val._tail,)), _END_NOTHING)
    elif isinstance(val, Pid):
        out += _pack_pid(val)
    elif isinstance(val, Port):
        out += _pack_port(val)
    elif isinstance(val, Export):
        out += _pack_export(val)
    elif isinstance(val, Fun):
        return _start_fun_value(val, out)
    elif isinstance(val, Reference):
        out += _pack_ref(val)
    elif type_val == bytes:
        out += _pack_binary(val, 8)
    elif isinstance(val, BitString):
        out += _pack_binary(val.value_, val.last_byte_bits_)
    else:
        return _Substitute(_substitute(val, encode_hook))
    return None


def _start_fun_value(val: Fun, out: bytearray) -> Optional[_EncFrame]:
    """Write ``NEW_FUN_EXT`` up to its free variables, which follow as
    children; ``Size`` is filled in once they are written."""
    free = val.free_
    if not isinstance(free, (list, tuple)) or len(free) > _MAX_FUN_FREE:
        raise PyCodecError("Fun free variables must be a list of at most 255")
    uniq = val.uniq_
    if not isinstance(uniq, bytes) or len(uniq) != 16:
        raise PyCodecError("Fun uniq must be 16 bytes")
    if type(val.arity_) is not int or not 0 <= val.arity_ <= 255:
        raise PyCodecError("Fun arity is out of range")
    if type(val.index_) is not int or not 0 <= val.index_ < 2**32:
        raise PyCodecError("Fun index is out of range")
    for name, field in (("OldIndex", val.old_index_), ("OldUniq", val.old_uniq_)):
        if type(field) is not int or not _MIN_SMALL <= field <= _MAX_SMALL:
            raise PyCodecError("Fun %s is out of range" % name)
    if not isinstance(val.module_, str):
        raise PyCodecError("Fun module must be an atom")
    if not isinstance(val.pid_, Pid):
        raise PyCodecError("Fun pid must be a Pid")
    size_at = len(out) + 1
    out.append(TAG_NEW_FUN_EXT)
    out += bytes(4)  # Size, filled in by _patch_fun_size
    out.append(val.arity_)
    out += uniq
    out += _U32.pack(val.index_)
    out += _U32.pack(len(free))
    out += _pack_atom(val.module_)
    out += _pack_int(val.old_index_)
    out += _pack_int(val.old_uniq_)
    out += _pack_pid(val.pid_)
    if not free:
        _patch_fun_size(out, size_at)
        return None
    return (val, iter(free), size_at)


def _patch_fun_size(out: bytearray, size_at: int) -> None:
    """Fill in the Size of a NEW_FUN_EXT that ends here: the bytes from the
    Size field to the end of the fun."""
    out[size_at : size_at + 4] = _U32.pack(len(out) - size_at)


# Returned by next() when a frame has no children left.
_DONE: Any = object()


def _encode(
    val: Any, encode_hook: EncodeHookType, max_depth: int, out: bytearray
) -> None:
    """Append the encoding of ``val`` to ``out``.

    Iterative: compound values wait on an explicit stack, at most
    ``max_depth`` of them, so neither Python's recursion limit nor the C
    stack bounds the nesting (as the decoders). A value that contains itself
    raises PyCodecError, and so does a chain of more than ``max_depth``
    substitutions (hooks that keep returning values with no encoding).
    """
    stack: list[_EncFrame] = []
    open_ids: set[int] = set()
    substitutions = 0
    while True:
        frame = _start_value(val, encode_hook, out)
        if isinstance(frame, _Substitute):
            substitutions += 1
            if substitutions > max_depth:
                raise PyCodecError(
                    "Value is substituted more than max_depth %d times" % max_depth
                )
            val = frame.value_
            continue
        substitutions = 0
        if frame is not None:
            if len(stack) >= max_depth:
                raise PyCodecError(
                    "Term is nested deeper than max_depth %d" % max_depth
                )
            key = id(frame[0])
            if key in open_ids:
                raise PyCodecError(
                    "Value contains itself (a %s)" % type(frame[0]).__name__
                )
            open_ids.add(key)
            stack.append(frame)
        # The next child of the innermost open value; close finished ones.
        while stack:
            container, children, end = stack[-1]
            val = next(children, _DONE)
            if val is not _DONE:
                break
            if end == _END_NIL:
                out.append(TAG_NIL_EXT)
            elif end >= 0:
                _patch_fun_size(out, end)
            stack.pop()
            open_ids.discard(id(container))
        else:
            return


def term_to_binary_2(
    val: Any, encode_hook: EncodeHookType, max_depth: int = DEFAULT_MAX_DEPTH
) -> bytes:
    """Encode a value without the 131 header byte.

    :param encode_hook: None or a dict with key value pairs (t,v) where t
        is a python type (as string, i.e. 'int' not int) and v a callable
        operating on an object of type t.
        Additionally, t may be 'catch_all' and v a callback which returns a
        representation for unknown object types.
    :param val: Almost any Python value
    :param max_depth: how deeply compound values may nest
    :return: bytes object with encoded data, but without a 131 header byte.
        None will be encoded as such and becomes Atom('undefined').
    :raises PyCodecError: for a value nested deeper than ``max_depth``, a
        value that contains itself, and a value with no encoding
    """
    out = bytearray()
    _encode(val, encode_hook, max_depth, out)
    return bytes(out)


def term_to_binary(val: Any, opt: OptionsType = None) -> bytes:
    """Prepend the 131 header byte to encoded data.
    :param val the value to encode
    :param opt: None or a dict of options:
        * "encode_hook": None or a dict with key value pairs (t,v) where t
          is a python type (as string, i.e. 'int' not int) and v a callable
          operating on an object of type t.
          Additionally, t may be 'catch_all' and v a callback which returns a
          representation for unknown object types.
        * "max_depth": how deeply compound values may nest (default 4096,
          as for decoding)
    :return:
        None will be encoded as such and becomes Atom('undefined').
    :raises PyCodecError: as :py:func:`term_to_binary_2`
    """
    if opt is None:
        opt = {}
    encode_hook = opt.get("encode_hook", None)
    max_depth = _positive_int_option(opt, "max_depth", DEFAULT_MAX_DEPTH)
    out = bytearray([ETF_VERSION_TAG])
    _encode(val, encode_hook, max_depth, out)
    return bytes(out)


__all__ = [
    "binary_to_term",
    "binary_to_term_2",
    "term_to_binary",
    "term_to_binary_2",
    "PyCodecError",
    "generic_serialize_object",
]
