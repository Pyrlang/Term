# Changelog

## Unreleased

- Decoding options (`atom`, `atom_call`, `byte_string`) and `decode_hook`
  apply to every nested term in both codecs. The Python codec used to apply
  them to the outermost term only. `atom_call` takes precedence over `atom`.
  `atom: "bytes"` gives the UTF-8 text in both codecs, also for Latin-1
  atoms. A non-callable `atom_call` or a `decode_hook` that is not a dict
  raises `PyCodecError`.
- Node names of decoded pids and references are always `term.Atom`, whatever
  the options; hooks do not see them. A pid or reference whose node is not
  an atom raises `PyCodecError`.
- The native codec decodes a zero-length `LIST_EXT` with a tail `T` as `T`,
  like the Python codec and OTP.
- Integers and strings encode as OTP writes them, in both codecs:
  `INTEGER_EXT` for the whole signed 32-bit range (the Python codec raised
  `struct.error` for 2^31..2^32-1, the native one wrote -2^31 as a bignum);
  bignums without a leading zero byte; strings of code points 0..255 and at
  most 65535 characters as Latin-1 `STRING_EXT` (both codecs wrote UTF-8
  bytes, so "é" arrived as two characters); `""` and `[]` as `NIL_EXT`; a
  255-element tuple as `SMALL_TUPLE_EXT` (native). The native decoder reads
  `STRING_EXT` as Latin-1 (it failed on bytes >= 128).
- New decode option `"bitstring": "tuple" | "BitString"` (default `"tuple"`,
  unchanged). With `"BitString"` a decoded bitstring encodes back to the same
  bitstring. `BitString` has equality, hash and repr. Both codecs reject a
  bitstring with 0 or more than 8 bits in the last byte, or with no bytes;
  8 bits make a plain binary (`bytes`), and unused low bits of the last byte
  are cleared on decode and encode, as OTP does.
- Decoding malformed input raises only `PyCodecError` in both codecs. The
  Python codec raised `IndexError`, `struct.error`, `UnicodeDecodeError`,
  `AssertionError`, `TypeError` or `zlib.error`, or silently decoded short
  reads. An exception raised by `decode_hook` or `atom_call`, and the
  `TypeError` of an unhashable map key, become the `__cause__` of the
  `PyCodecError` (the native codec used to drop them); the message of the
  latter names the key's type.
- `ImproperList(elements, tail)` keeps a falsy tail (`0`, `None`, `""`);
  `[1|0]` and `[1|undefined]` decoded as lists with the wrong tail.
- Resource limits on decoding, the same in both codecs. Decoding is
  iterative, so deep nesting no longer overflows the native stack (the
  native codec crashed the interpreter below 1000 levels in a debug build)
  or hits Python's recursion limit (about 350 levels). New options:
  `max_depth` (default 4096 nested compound terms) and `max_size` (default
  256 MiB, the most a compressed term may declare). Counts in the input are
  checked against the bytes that remain before anything is allocated (the
  native codec aborted on a list or tuple claiming 2^31 elements). A
  compressed term is inflated incrementally and only up to its declared
  size, and its zlib stream must be complete: a cut-off checksum used to be
  accepted.
- Encoding is iterative too, with the same `max_depth` option (default
  4096): deeper values raise `PyCodecError` in both codecs instead of
  `RecursionError` (Python, about 350 levels) or a native stack overflow
  (below 1000 levels in a debug build). A value that contains itself, and
  hooks (`catch_all`, `__etf__`) that keep returning values with no encoding,
  raise `PyCodecError` instead of recursing until the stack runs out. Dicts
  are encoded from a snapshot of their items in the Python codec too.
- New `term.Port(node_name, id, creation)`. Both codecs decode `PORT_EXT`,
  `NEW_PORT_EXT` and `V4_PORT_EXT` (64-bit ids, mandatory between OTP 26+
  nodes) and encode every `Port` as `V4_PORT_EXT`, as OTP does. A port
  from an OTP node used to raise `Unknown tag`. `PORT_EXT` with a creation
  above 3 raises `PyCodecError`, as in OTP.
- References: both codecs decode `REFERENCE_EXT` (one word) and reject what
  OTP 29 rejects: more than 5 ID words, `NEW_REFERENCE_EXT` with no words or
  a first word of more than 18 bits, an 8-bit creation above 3 in
  `PID_EXT`, `REFERENCE_EXT` and `NEW_REFERENCE_EXT`. A`n  `NEWER_REFERENCE_EXT` with no ID words is rejected too (OTP 29 accepts it,
  reading past the term). Encoding a `Reference` whose ID is not 1..5 whole
  words, or a `Pid` field beyond 32 bits, raises `PyCodecError` (the Python
  codec raised `struct.error` or wrote a broken term).
- `Reference.create` numbers references with a per-process counter plus 32
  random bits, so two created references are never equal (it used a clock
  value plus a random number).
