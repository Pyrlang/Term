Erlang Term and Codec for Python
================================

This project is a part of http://github.com/Pyrlang/Pyrlang
but does not depend on it and can be used separately.

The Term library adds support classes to represent Erlang terms in Python 
and implements a codec for encoding and decoding data in Erlang
External Term Format (abbreviated ETF) written in Python and a native 
and (most likely) safe Python extension written in Rust. 

The extension or Python implementation is selected automatically when you import 
`term.codec` and all API is available via `term.codec` module. If native 
extension was not found, a warning will be logged and the Python implementation
will be used.

## Installing

### From PyPI

```
pip install pyrlang-term
```

Wheels are published for Linux, Windows and macOS; each works on every
CPython from 3.11 on (abi3) and contains the native codec. Where no wheel
fits, pip builds from source: with a Rust toolchain
(https://www.rust-lang.org/tools/install) you get the native codec,
without one the Python codec only.

### From Source

1. Clone [Term](https://github.com/Pyrlang/Term) repository
2. In the Term directory: `pip install -e . --config-settings editable_mode=compat`
   (builds the native codec in place when Rust is available)

## Testing

```
pip install pytest
python -m pytest test
```

Tests marked `erlang` let a real Erlang/OTP judge the codecs; they use `erl`
from `PATH`, or the one named by `$PYRLANG_ERL`, and skip when there is none.
`make check` runs every check required before a commit.


## Performance

Median time of one call in microseconds: the Python codec, the native (Rust)
codec, and Erlang/OTP's own `binary_to_term/1` and `term_to_binary/1` on the
same bytes. "Rust vs Python" is how many times faster the native codec is
than the Python codec, "OTP vs Rust" how many times faster OTP is than the
native codec; below 1 the first of the two is the slower one. One call
handles the whole workload (`list_100k_ints` is 100 000 integers).

Measured on Linux (WSL2, Intel i9-14900KF, one pinned core) with CPython
3.13.13, Erlang/OTP 29.1.2 and a release build of the native codec (rustc
1.100). Windows gives the same picture.

| workload | op | Python µs | Rust µs | OTP µs | Rust vs Python | OTP vs Rust |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| atoms_200_unicode | decode | 125 | 19.9 | 5.18 | 6.30× | 3.83× |
| atoms_200_unicode | encode | 63.9 | 7.42 | 1.55 | 8.61× | 4.80× |
| bignums_1000 | decode | 788 | 167 | 33.6 | 4.73× | 4.95× |
| bignums_1000 | encode | 352 | 330 | 14.6 | 1.07× | 22.6× |
| binary_1mb | decode | 23.5 | 20.1 | 26.7 | 1.17× | 0.756× |
| binary_1mb | encode | 495 | 460 | 28.7 | 1.08× | 16.0× |
| dist_control | decode | 4.15 | 1.45 | 0.115 | 2.87× | 12.6× |
| dist_control | encode | 2.04 | 0.610 | 0.071 | 3.35× | 8.54× |
| fixtures_golden | decode | 23808 | 1682 | 696 | 14.2× | 2.42× |
| fixtures_golden | encode | 12833 | 2254 | 574 | 5.69× | 3.93× |
| fixtures_otp | decode | 4491 | 1167 | 253 | 3.85× | 4.61× |
| fixtures_otp | encode | 2327 | 660 | 69.1 | 3.52× | 9.55× |
| floats_10k | decode | 5512 | 269 | 104 | 20.5× | 2.60× |
| floats_10k | encode | 2459 | 330 | 42.5 | 7.45× | 7.78× |
| gen_call | decode | 14.5 | 3.37 | 0.435 | 4.31× | 7.74× |
| gen_call | encode | 9.64 | 1.84 | 0.261 | 5.23× | 7.06× |
| list_100k_ints | decode | 43646 | 3396 | 637 | 12.9× | 5.33× |
| list_100k_ints | encode | 27173 | 3192 | 419 | 8.51× | 7.61× |
| map_10k_atom_keys | decode | 11620 | 1251 | 1133 | 9.29× | 1.10× |
| map_10k_atom_keys | encode | 7023 | 1042 | 291 | 6.74× | 3.59× |
| nested_1000 | decode | 671 | 61.2 | 8.66 | 11.0× | 7.07× |
| nested_1000 | encode | 425 | 70.0 | 7.01 | 6.07× | 9.99× |
| pids_refs_1000 | decode | 3676 | 427 | 127 | 8.60× | 3.35× |
| pids_refs_1000 | encode | 1699 | 484 | 29.0 | 3.51× | 16.7× |
| string_65535 | decode | 4.74 | 35.2 | 252 | 0.135× | 0.140× |
| string_65535 | encode | 4.48 | 52.5 | 189 | 0.085× | 0.278× |
| tuples_10k | decode | 23251 | 1548 | 436 | 15.0× | 3.55× |
| tuples_10k | encode | 15949 | 1530 | 295 | 10.4× | 5.18× |

- OTP builds terms on a process heap with no foreign-function calls; our
  codecs build CPython objects. The comparison shows the distance to OTP,
  it is not like for like.
- `string_65535`: an Erlang string is a list of integers, which OTP has to
  build or walk element by element; we produce one flat `str`. With the same
  bytes as a binary OTP is as fast as on `binary_1mb`. On this workload the
  Python codec is faster than the native one; that is a known defect.
- `fixtures_golden` and `fixtures_otp` are the test corpora (`test/fixtures`),
  every file of the set in one call.

Run it yourself (needs `erl` on `PATH` or `$PYRLANG_ERL`, and cargo; it
builds its own release codec and leaves the installed one alone):

```
python test/bench/run.py --seconds 1 --cpu 4
```

## Atoms

The native representation of atoms are found in `term.atom`. There are Two
classes, `Atom` and `StrictAtom`. `Atom` is the default, it will become an
atom when converting back to `etf`, however it evaluates as string so it's
possible to use a map with atom keys as keyword argument.

The drawback of this is if you may have a map with both atoms and string
/binaries with the same content

```erlang
#{foo => <<"atom">>, "foo" => <<"list">>}
```
Python sees these two keys as one, so the codec refuses the map instead of
dropping an entry:
```python
In [1]: from term import codec

In [2]: data = bytes([131,116,0, ...])

In [3]: codec.binary_to_term(data)
PyCodecError: Map key of type str equals an earlier key of the map in Python
```

To allow for this we've added another atom type `StrictAtom` that will give you:
```python
In [4]: codec.binary_to_term(data, {'atom': "StrictAtom"})
Out[4]: ({StrictAtom('foo'): b'atom', 'foo': b'list'}, b'')

```
Still `StrictAtom('foo') == 'foo'` so it you need something different still, you
can put in your custom atom class

```python
In [5]: class A:
   ...:     def __init__(self, s):
   ...:         self._s = s
   ...:     def __repr__(self):
   ...:         return 'A({})'.format(self._s)
   ...:

In [6]: codec.binary_to_term(data, {'atom_call': A})
Out[6]: ({A(foo): b'atom', 'foo': b'list'}, b'')

```
The `'atom_call'` option takes any callable that takes a string as input, and
the return value will be used for the atom representation. Only `Atom` and
`StrictAtom` can be natively parsed back to atom when decoded. If you roll your
own, make sure to use `encode_hook` when encoding.

More Documentation
-------------

Here: https://pyrlang.github.io/Term/
