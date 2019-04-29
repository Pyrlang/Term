""" Adapter module which attempts to import native (Rust) codec implementation
    and then if import fails, uses Python codec implementation which is slower
    but always works.
"""
import logging

LOG = logging.getLogger("term")


try:
    import term.native_codec_impl as co_impl
except ImportError:
    LOG.warning("Native term ETF codec library import failed, falling back to slower Python impl")
    import term.py_codec_impl as co_impl


def binary_to_term(data: bytes, options=None):
    """
    Strip 131 header and unpack if the data was compressed.

    :param data: The incoming encoded data with the 131 byte
    :param options: Options dict (pending design)
                    * "atom": "str" | "bytes" | "Atom" (default "Atom").
                      Returns atoms as strings, as bytes or as atom.Atom objects.
                    * "byte_string": "str" | "bytes" (default "str").
                      Returns 8-bit strings as Python str or bytes.
    :raises PyCodecError: when the tag is not 131, when compressed
                          data is incomplete or corrupted
    :returns: Remaining unconsumed bytes
    """
    return co_impl.binary_to_term(data, options)


def term_to_binary(term: object, options=None):
    """
    Prepend the 131 header byte to encoded data.

    :param opt: None or dict of options: "encode_hook" is a callable which
                will return representation for unknown object types. Returning
                None will be encoded as such and becomes Atom('undefined').
    :returns: Bytes, the term object encoded with erlang binary term format
    """
    return co_impl.term_to_binary(term, options)

PyCodecError = co_impl.PyCodecError

# aliases

encode = pack = dumps = term_to_binary
decode = unpack = loads = binary_to_term

__all__ = ['term_to_binary', 'binary_to_term', 'PyCodecError',
           'encode', 'decode',
           'pack', 'unpack',
           'dumps', 'loads']
