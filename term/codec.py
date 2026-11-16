"""The codec: Erlang External Term Format to Python values and back.

This module is the public interface. It uses the native (Rust) codec when
the extension module was built, and the Python codec
(:py:mod:`term.py_codec_impl`) otherwise; both give the same results.

Decode options
--------------

``binary_to_term`` and ``binary_to_term_2`` take a dict of options. They
apply at every nesting level of the term.

``"atom"``
    ``"Atom"`` (default), ``"StrictAtom"``, ``"str"`` or ``"bytes"``: what
    an Erlang atom becomes. ``true``, ``false`` and ``undefined`` always
    become ``True``, ``False`` and ``None``.
``"atom_call"``
    A callable that gets the atom's text and returns the value to use for
    it. Takes precedence over ``"atom"``.
``"byte_string"``
    ``"str"`` (default), ``"bytes"`` or ``"int_list"``: what a list of bytes
    that Erlang sent as ``STRING_EXT`` becomes.
``"bitstring"``
    ``"tuple"`` (default): a bitstring becomes ``(bytes, last_byte_bits)``.
    ``"BitString"``: it becomes a :py:class:`~term.bitstring.BitString`,
    which encodes back to the same bitstring.
``"decode_hook"``
    A dict of type name to callable. Every decoded value whose type has
    that name is replaced by what the callable returns for it.
``"atom_cache"``
    A list or tuple of atom texts that ``ATOM_CACHE_REF`` refers to, for
    terms that follow a distribution header. Without it such a reference is
    an error.
``"max_depth"``
    How deeply compound terms may nest (default 4096).
``"max_size"``
    The largest size in bytes a compressed term may declare (default
    256 MiB).

Encode options
--------------

``"encode_hook"``
    A dict of type name (``"int"``, not ``int``) to callable; a value of
    that type is replaced by what the callable returns before it is
    encoded. The key ``"catch_all"`` is used for values that have no
    encoding of their own. A single callable instead of a dict means
    ``{"catch_all": callable}``.
``"max_depth"``
    How deeply compound values may nest (default 4096).

A value with no encoding of its own and no ``"catch_all"`` hook is encoded
as what its ``__etf__()`` method returns, or else as the tuple
``(ClassName, Fields)`` of its public attributes.
"""

import logging
from types import ModuleType
from typing import Any, Callable, Optional

from term.basetypes import BaseTerm, Term

LOG = logging.getLogger("term")

# Either implementation; their function signatures differ slightly (see
# native_codec_impl.pyi), so the common type is the plain module.
co_impl: ModuleType
try:
    import term.native_codec_impl as co_impl
except ImportError:
    LOG.warning(
        "Native term ETF codec library import failed, falling back to slower Python impl"
    )
    import term.py_codec_impl as co_impl


# Options and hooks carry arbitrary user values and callables, hence Any.
_Options = Optional[dict[str, Any]]
_Hooks = Optional[dict[str, Callable[[Any], Any]]]


def binary_to_term(
    data: bytes, options: _Options = None, decode_hook: _Hooks = None
) -> tuple[Term, bytes]:
    """Decode one term that starts with the version byte 131; a compressed
    term is inflated.

    :param data: the encoded term; more bytes may follow it
    :param options: the decode options listed in the module description
    :param decode_hook: the ``"decode_hook"`` option, given separately
    :raises PyCodecError: when the first byte is not 131, on any malformed
        or truncated input, when a limit is exceeded, and when a hook or
        ``"atom_call"`` raises (the original exception is the ``__cause__``)
    :returns: the value, and the bytes that follow the term
    """
    opt = options if options else {}
    if decode_hook:
        opt["decode_hook"] = decode_hook
    return co_impl.binary_to_term(data, opt)


def term_to_binary(
    term: object, options: _Options = None, encode_hook: _Hooks = None
) -> bytes:
    """Encode a value, starting with the version byte 131.

    ``None`` is encoded as the atom ``undefined``, ``True`` and ``False`` as
    ``true`` and ``false``.

    :param term: the value to encode
    :param options: the encode options listed in the module description
    :param encode_hook: the ``"encode_hook"`` option, given separately
    :raises PyCodecError: for a value nested deeper than ``"max_depth"``, a
        value that contains itself, and a value that cannot be encoded
    :returns: the encoded term
    """
    opt = options if options else {}
    if options and hasattr(options.get("encode_hook", {}), "__call__"):
        # legacy encode_hook as single function transformed to 'catch_all' in new encode_hook dict
        opt["encode_hook"] = {"catch_all": options.get("encode_hook")}
    elif encode_hook:
        opt["encode_hook"] = encode_hook
    return co_impl.term_to_binary(term, opt)


def binary_to_term_2(
    data: bytes, options: _Options = None, decode_hook: _Hooks = None
) -> tuple[Term, bytes]:
    """Decode a term that has no version byte 131, as the terms that follow
    a distribution header; with the option ``"atom_cache"`` (a list of atom
    texts) ``ATOM_CACHE_REF`` refers to its entries.

    :param data: the encoded term; more bytes may follow it
    :param options: as for :py:func:`binary_to_term`
    :param decode_hook: as for :py:func:`binary_to_term`
    :raises PyCodecError: as :py:func:`binary_to_term`
    :returns: the value, and the bytes that follow the term
    """
    opt = options if options else {}
    if decode_hook:
        opt["decode_hook"] = decode_hook
    return co_impl.binary_to_term_2(data, opt)


def term_to_binary_2(
    term: object, options: _Options = None, encode_hook: _Hooks = None
) -> bytes:
    """Encode a value without the version byte 131; otherwise as
    :py:func:`term_to_binary`.

    :param term: the value to encode
    :param options: as for :py:func:`term_to_binary`
    :param encode_hook: as for :py:func:`term_to_binary`
    :raises PyCodecError: as :py:func:`term_to_binary`
    :returns: the encoded term
    """
    # The two implementations take different arguments for their own
    # term_to_binary_2; dropping the header byte works with both.
    return term_to_binary(term, options, encode_hook)[1:]


PyCodecError = co_impl.PyCodecError

# aliases

encode = pack = dumps = term_to_binary
decode = unpack = loads = binary_to_term

__all__ = [
    "term_to_binary",
    "binary_to_term",
    "term_to_binary_2",
    "binary_to_term_2",
    "PyCodecError",
    "encode",
    "decode",
    "pack",
    "unpack",
    "dumps",
    "loads",
]
