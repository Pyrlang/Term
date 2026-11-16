# Term

Term represents Erlang terms as Python values and converts them to and from
the Erlang External Term Format (ETF), the format of `term_to_binary/1`,
`binary_to_term/1` and the Erlang distribution protocol.

- Every term type that an Erlang/OTP 25 to 29 node sends is decoded and
  encoded, including pids, ports and references of the current sizes,
  bitstrings, funs and native records.
- Two codecs with the same results: one in Python, and a native one in Rust
  that is several times faster. The native one is used when it is installed.
- Input is treated as untrusted: malformed, truncated, too deep or too large
  input raises `PyCodecError` and nothing else.
- Python 3.11 or newer; no dependencies.

Term is one of three projects that work together and can be used apart:

- {{ pyrlang_site }}: an Erlang node in Python. It uses Term for
  every message.
- Term: this project.
- {{ epmd_site }}: an Erlang Port Mapper Daemon in Python.

## Installing

```sh
pip install pyrlang-term
```

Wheels are published for Linux, Windows and macOS. One wheel serves every
CPython from 3.11 on and contains the native codec. Where no wheel fits, pip
builds from source: with a [Rust toolchain](https://rust-lang.org/tools/install/)
you get the native codec, without one the Python codec only.

From a clone of <https://github.com/Pyrlang/Term>:

```sh
pip install -e . --config-settings editable_mode=compat
```

## A first example

Everything goes through {py:mod}`term.codec`:

```pycon
>>> from term import Atom, codec
>>> data = codec.term_to_binary((Atom("ok"), 1, [2.5, b"binary"]))
>>> data
b'\x83h\x03w\x02oka\x01l\x00\x00\x00\x02F@\x04\x00\x00\x00\x00\x00\x00m\x00\x00\x00\x06binaryj'
>>> codec.binary_to_term(data)
((Atom('ok'), 1, [2.5, b'binary']), b'')
```

`binary_to_term` returns the value and the bytes that follow the term, so
several terms in one buffer can be decoded one after another.

`term_to_binary_2` and `binary_to_term_2` do the same without the leading
version byte 131.

Which codec is in use:

```pycon
>>> codec.co_impl.__name__ in ("term.native_codec_impl", "term.py_codec_impl")
True
```

When the native codec cannot be imported, `term.codec` logs one warning on
the logger `term` and uses the Python codec.

## Errors

Both directions raise {py:exc}`term.codec.PyCodecError`:

```pycon
>>> codec.binary_to_term(b"\x83h\x02a\x01")
Traceback (most recent call last):
    ...
PyCodecError: Incomplete data: 1 bytes needed at offset 5, 0 left
```

The message is the Python codec's; the native codec words it differently.
The class is that of the codec in use, so always catch
`codec.PyCodecError`.

## Performance

```{include} ../../README.md
:start-after: <!-- performance-start -->
:end-before: <!-- performance-end -->
```

```{toctree}
:maxdepth: 2
:caption: Contents

data_types
reference
known-differences
changelog
```
