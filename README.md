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

If you just run 
```
pip install pyrlang-term
```
the pure python version will be installed unless there exists a pre built binary.

If you want to build the native one, you'll need rust and a few more packages.

To install rust (from https://www.rust-lang.org/tools/install):

```
curl https://sh.rustup.rs -sSf | sh
```

Then install the build requirements before installing pyrlang-term:

```
pip install setuptools-rust semantic_version
pip install pyrlang-term
```

### From Source

1. Clone [Term](https://github.com/Pyrlang/Term) repository
2. Install Term from source: Go to Term directory and `pip install -e .`

## Testing

To run the tests:

```
python -m unittest discover test
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
Then you'll get
```python
In [1]: from term import codec

In [2]: data = bytes([131,116,0, ...])

In [3]: codec.binary_to_term(data)
Out[3]: ({Atom('foo'): b'list'}, b'')
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
