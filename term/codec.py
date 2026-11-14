"""Adapter module which attempts to import native (Rust) codec implementation
and then if import fails, uses Python codec implementation which is slower
but always works.
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
    """
    Strip 131 header and unpack if the data was compressed.

    :param data: The incoming encoded data with the 131 byte
    :param options: None or Options dict (pending design)
                    * "atom": "str" | "bytes" | "Atom" (default "Atom").
                      Returns atoms as strings, as bytes or as atom.Atom objects.
                    * "atom_call": callabe object that returns the atom representation
                    * "byte_string": "str" | "bytes" | "int_list" (default "str").
                      Returns 8-bit strings as Python str, bytes or list of integers.
    :param decode_hook:
                Key/value pairs t: str,f : callable, s.t. f(v) is run before encoding
                for values v of type t. This allows for overriding the built-in encoding.
                "catch_all": f is a callable which will return representation for unknown
                object types.
    :raises PyCodecError: when the tag is not 131, when compressed
                          data is incomplete or corrupted
    :returns: Value and Remaining unconsumed bytes
    """
    opt = options if options else {}
    if decode_hook:
        opt["decode_hook"] = decode_hook
    return co_impl.binary_to_term(data, opt)


def term_to_binary(
    term: object, options: _Options = None, encode_hook: _Hooks = None
) -> bytes:
    """
    Prepend the 131 header byte to encoded data.
    :param options: None or a dict of options with key/values "encode_hook": f where f
                is a callable which will return representation for unknown object types.
                This is kept for backward compatibility, and is equivalent to
                    encode_hook={"catch_all": f}
                None will be encoded as such and becomes Atom('undefined').
    :param encode_hook:
                Key/value pairs t: str,f : callable, s.t. f(v) is run before rust encoding
                for values of the type t. This allows for overriding the built-in encoding.
                "catch_all": f is a callable which will return representation for unknown
                object types.
    :returns: Bytes, the term object encoded with erlang binary term format
    """
    opt = options if options else {}
    if options and hasattr(options.get("encode_hook", {}), "__call__"):
        # legacy encode_hook as single function transformed to 'catch_all' in new encode_hook dict
        opt["encode_hook"] = {"catch_all": options.get("encode_hook")}
    elif encode_hook:
        opt["encode_hook"] = encode_hook
    return co_impl.term_to_binary(term, opt)


PyCodecError = co_impl.PyCodecError

# aliases

encode = pack = dumps = term_to_binary
decode = unpack = loads = binary_to_term

__all__ = [
    "term_to_binary",
    "binary_to_term",
    "PyCodecError",
    "encode",
    "decode",
    "pack",
    "unpack",
    "dumps",
    "loads",
]
