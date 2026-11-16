# Data types

How Erlang terms and Python values map to each other. The examples run
with either codec.

```pycon
>>> from term import Atom, BitString, ImproperList, codec
>>> def roundtrip(value, options=None):
...     return codec.binary_to_term(codec.term_to_binary(value), options)[0]
```

## Decoding: Erlang to Python

| Erlang | Python | Notes |
| --- | --- | --- |
| `atom()` | {py:class}`~term.atom.Atom` | A `str` subclass. Options `"atom"` and `"atom_call"` choose another type. |
| `true`, `false`, `undefined` | `True`, `False`, `None` | Always, whatever the atom options say. |
| `integer()` | `int` | Any size. |
| `float()` | `float` | NaN and infinities are rejected, as in Erlang. |
| `binary()` | `bytes` | |
| `bitstring()` | `(bytes, last_byte_bits)` | Or {py:class}`~term.bitstring.BitString` with the option `"bitstring": "BitString"`. |
| `tuple()` | `tuple` | |
| `list()` | `list` | |
| list of bytes sent as a string | `str` | See [Strings](#strings). Option `"byte_string"`. |
| improper list | {py:class}`~term.list.ImproperList` | A `list` whose last element is the tail. |
| `map()` | `dict` | See [Maps](#maps). |
| `pid()` | {py:class}`~term.pid.Pid` | |
| `port()` | {py:class}`~term.port.Port` | |
| `reference()` | {py:class}`~term.reference.Reference` | |
| `fun M:F/A` | {py:class}`~term.fun.Export` | |
| `fun(...) -> ... end` | {py:class}`~term.fun.Fun` | Cannot be called from Python; can be sent back. |
| native record (OTP 29) | {py:class}`~term.record.Record` | |

## Encoding: Python to Erlang

| Python | Erlang | Notes |
| --- | --- | --- |
| `Atom` | `atom()` | At most 255 characters. |
| `True`, `False`, `None` | `true`, `false`, `undefined` | |
| `int` | `integer()` | |
| `float` | `float()` | |
| `bytes` | `binary()` | |
| `BitString` | `bitstring()` | |
| `tuple` | `tuple()` | |
| `list` | `list()` | |
| `str` | `string()`, a list of code points | |
| `ImproperList` | improper list | |
| `dict` | `map()` | |
| `Pid`, `Port`, `Reference`, `Export`, `Fun`, `Record` | the same term | |
| any other object | see [Other objects](#other-objects) | |

## Strings

An Erlang string is a list of integers, and nothing in the encoded bytes says
whether a list was meant as text. Erlang encodes a list of up to 65535
integers that are all in 0..255 in a compact form (`STRING_EXT`); such a
list is decoded to a `str`. Every other list, including a string with a
character above 255, is decoded to a `list` of integers.

```pycon
>>> roundtrip("hello")
'hello'
>>> roundtrip("price: 5 €")
[112, 114, 105, 99, 101, 58, 32, 53, 32, 8364]
```

So a short list of small integers sent by Erlang, `[1, 2, 3]`, arrives as
the string `'\x01\x02\x03'`. The option `"byte_string"` asks for `bytes`
or a list of integers instead:

```pycon
>>> roundtrip("hello", {"byte_string": "int_list"})
[104, 101, 108, 108, 111]
>>> roundtrip("hello", {"byte_string": "bytes"})
b'hello'
```

{py:func}`term.list.list_to_unicode_str` turns a list of code points into a
`str`. When both sides are yours, send text as a UTF-8 binary: binaries
arrive as `bytes` whatever their content.

## Atoms

An `Atom` is a `str`, so `Atom("ok") == "ok"`. That is convenient, and it
means an atom and a string of the same text are one dict key. `StrictAtom`
hashes differently and can stand next to the string:

```pycon
>>> roundtrip(Atom("ok"))
Atom('ok')
>>> roundtrip(Atom("ok"), {"atom": "StrictAtom"})
StrictAtom('ok')
>>> roundtrip(Atom("ok"), {"atom": "str"})
'ok'
>>> roundtrip(Atom("ok"), {"atom_call": lambda text: ("atom", text)})
('atom', 'ok')
```

## Maps

A map becomes a `dict`. Keys that are different in Erlang and equal in
Python (`1` and `1.0`, `true` and `1`, an atom and a string of the same
text) would silently merge into one entry, so such a map is refused:

```pycon
>>> codec.binary_to_term(b"\x83t\x00\x00\x00\x02a\x01a\x01F?\xf0\x00\x00\x00\x00\x00\x00a\x02")
Traceback (most recent call last):
    ...
PyCodecError: Map key of type float equals an earlier key of the map in Python
```

A key that Python cannot hash (a list, a map) is refused as well.

## Bitstrings and improper lists

```pycon
>>> roundtrip(BitString(b"\xff\xe0", 3))
(b'\xff\xe0', 3)
>>> roundtrip(BitString(b"\xff\xe0", 3), {"bitstring": "BitString"})
BitString(b'\xff\xe0', 3)
>>> tail = roundtrip(ImproperList([1, 2], Atom("tail")))
>>> type(tail).__name__, tail
('ImproperList', [1, 2, Atom('tail')])
```

## Other objects

A value of any other type is encoded as, in this order:

1. what the `"catch_all"` entry of the encode hook returns for it;
2. what its `__etf__()` method returns;
3. the tuple `{ClassName, #{Field => Value}}` of its class name and public
   attributes, both as binaries.

```pycon
>>> class Money:
...     def __init__(self, amount):
...         self.amount = amount
...     def __etf__(self):
...         return (Atom("money"), self.amount)
>>> roundtrip(Money(5))
(Atom('money'), 5)
```

An encode hook replaces values by the name of their type before they are
encoded, and a decode hook does the same after decoding:

```pycon
>>> import datetime
>>> hook = {"date": lambda d: (d.year, d.month, d.day)}
>>> codec.binary_to_term(codec.term_to_binary(datetime.date(2026, 1, 2), None, hook))[0]
(2026, 1, 2)
>>> codec.binary_to_term(codec.term_to_binary((1, (2,))), None, {"tuple": list})[0]
[1, [2]]
```

## Limits

Input comes from the network, so both codecs bound what a term can cost:

- `"max_depth"` (default 4096): how deeply compound terms may nest, for
  decoding and encoding.
- `"max_size"` (default 256 MiB): the size a compressed term may declare.
- Counts in the input (list length, tuple arity, map size) are checked
  against the bytes that are left before anything is allocated.

```pycon
>>> deep = []
>>> for _ in range(5000):
...     deep = [deep]
>>> codec.term_to_binary(deep)
Traceback (most recent call last):
    ...
PyCodecError: Term is nested deeper than max_depth 4096
```

All options are listed with {py:mod}`term.codec`. Where the codec knowingly
differs from Erlang/OTP, [Known differences](known-differences.md) says so.
