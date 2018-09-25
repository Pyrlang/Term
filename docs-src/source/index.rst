Pyrlang Term Library
====================

Term is a Python 3.5 library which supports Erlang Term encoding, decoding and
representation as Python values. There are identical implementations of codec
in Python and in Rust, if your machine doesn't have Rust compiler installed,
the library.

This library has no dependencies on other parts of Pyrlang project and can be
used standalone.

Important APIs are:

.. code-block:: python

    from term import codec, Atom
    t = codec.term_to_binary((1, Atom('ok')))
    # Function term_to_binary will prepend a 131 byte tag
    # Function term_to_binary_2 encodes without a leading 131 byte

    (val, tail) = codec.binary_to_term(bytes)
    # Returns a pair: value and remaining bytes
    # Function binary_to_term strips leading 131 byte and also handles
    # decompression of an eventually compressed term
    # Function binary_to_term_2 decodes without a leading 131 byte

.. toctree::
    :maxdepth: 2
    :caption: Contents

    data_types
    term.atom
    term.bitstring
    term.erl_typing
    term.fun
    term.list
    term.pid
    term.py_codec_impl
    term.reference
