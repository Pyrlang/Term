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


def binary_to_term(data: bytes, options={}, decode_hook=None):
    """
    Strip 131 header and unpack if the data was compressed.

    :param data: The incoming encoded data with the 131 byte
    :param options: Options dict (pending design)
                    * "atom": "str" | "bytes" | "Atom" (default "Atom").
                      Returns atoms as strings, as bytes or as atom.Atom objects.
                    * "byte_string": "str" | "bytes" (default "str").
                      Returns 8-bit strings as Python str or bytes.
    :param decode_hook: 
                Key/value pairs t: str,f : callable, s.t. f(v) is run before encoding
                for values v of type t. This allows for overriding the built-in encoding.
                "catch_all": f is a callable which will return representation for unknown
                object types.
    :raises PyCodecError: when the tag is not 131, when compressed
                          data is incomplete or corrupted
    :returns: Remaining unconsumed bytes
    """
    if decode_hook is not None:
        options['decode_hook'] == decode_hook
    return co_impl.binary_to_term(data, options)


def term_to_binary(term: object, options={}, encode_hook=None):
    """
    Prepend the 131 header byte to encoded data.
    :param options: {}
                Alternatively, a dict of options with key/values "encode_hook": f where f
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
    if hasattr(options.get('encode_hook', {}) , '__call__'):
        options['encode_hook'] = {'catch_all': options.get('encode_hook')}
    elif encode_hook is not None:
        options['encode_hook'] = encode_hook
    return co_impl.term_to_binary(term, options)

PyCodecError = co_impl.PyCodecError

# aliases

encode = pack = dumps = term_to_binary
decode = unpack = loads = binary_to_term

__all__ = ['term_to_binary', 'binary_to_term', 'PyCodecError',
           'encode', 'decode',
           'pack', 'unpack',
           'dumps', 'loads']
