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
| atoms_200_unicode | decode | 116 | 16.0 | 4.98 | 7.24× | 3.21× |
| atoms_200_unicode | encode | 58.8 | 4.34 | 1.45 | 13.6× | 3.00× |
| bignums_1000 | decode | 737 | 139 | 31.7 | 5.31× | 4.38× |
| bignums_1000 | encode | 325 | 130 | 13.9 | 2.51× | 9.32× |
| binary_1mb | decode | 21.1 | 18.2 | 25.1 | 1.16× | 0.727× |
| binary_1mb | encode | 443 | 28.9 | 26.9 | 15.3× | 1.08× |
| dist_control | decode | 3.97 | 0.401 | 0.108 | 9.89× | 3.72× |
| dist_control | encode | 1.92 | 0.234 | 0.069 | 8.18× | 3.39× |
| fixtures_golden | decode | 21786 | 506 | 661 | 43.0× | 0.766× |
| fixtures_golden | encode | 11599 | 639 | 545 | 18.1× | 1.17× |
| fixtures_otp | decode | 4105 | 549 | 238 | 7.48× | 2.30× |
| fixtures_otp | encode | 2097 | 236 | 65.9 | 8.89× | 3.58× |
| floats_10k | decode | 5123 | 103 | 97.3 | 49.9× | 1.06× |
| floats_10k | encode | 2204 | 95.8 | 40.1 | 23.0× | 2.39× |
| gen_call | decode | 13.4 | 1.45 | 0.424 | 9.24× | 3.42× |
| gen_call | encode | 8.69 | 0.827 | 0.254 | 10.5× | 3.26× |
| list_100k_ints | decode | 40101 | 1458 | 602 | 27.5× | 2.42× |
| list_100k_ints | encode | 24955 | 964 | 400 | 25.9× | 2.41× |
| map_10k_atom_keys | decode | 10741 | 1060 | 1081 | 10.1× | 0.980× |
| map_10k_atom_keys | encode | 6354 | 598 | 271 | 10.6× | 2.20× |
| nested_1000 | decode | 619 | 35.0 | 8.03 | 17.7× | 4.35× |
| nested_1000 | encode | 388 | 50.2 | 6.72 | 7.72× | 7.47× |
| pids_refs_1000 | decode | 3406 | 371 | 129 | 9.18× | 2.88× |
| pids_refs_1000 | encode | 1576 | 138 | 28.3 | 11.4× | 4.87× |
| string_65535 | decode | 4.50 | 4.05 | 230 | 1.11× | 0.018× |
| string_65535 | encode | 4.20 | 2.55 | 178 | 1.65× | 0.014× |
| tuples_10k | decode | 21954 | 1313 | 415 | 16.7× | 3.16× |
| tuples_10k | encode | 14450 | 656 | 282 | 22.0× | 2.33× |

- The native codec is faster than the Python codec on every workload, and
  within 10x of OTP on all of them; it is about as fast as OTP on large
  binaries and on decoding floats and maps, and the slowest relative to
  OTP on bignum encoding (Python's `int` has no cheap byte export in the limited API).
- OTP builds terms on a process heap with no foreign-function calls; our
  codecs build CPython objects. The comparison shows the distance to OTP,
  it is not like for like.
- `string_65535`: an Erlang string is a list of integers, which OTP has to
  build or walk element by element; we produce one flat `str`. With the same
  bytes as a binary OTP is as fast as on `binary_1mb`.
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

## Documentation

Data types, codec options, the API reference and the known differences
from Erlang/OTP: https://pyrlang.clau.se/term/
