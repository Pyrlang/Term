# Changelog

## 2.0 (2026-11-16)

- Documentation rebuilt (Sphinx, Furo, MyST) and rewritten for the current
  code: data types, codec options, limits; every example on the pages is
  run by the tests. It moves to https://pyrlang.clau.se/term/; generated
  HTML is no longer kept in the repository.
- The native codec costs less per call: the term classes are imported once
  per process instead of once per call, and options `None` or `{}` are not
  parsed at all. Decoding a small term such as a distribution control
  message takes a third of the time it did, encoding one about three
  quarters.
- The native codec decodes and encodes `STRING_EXT` strings about ten
  times faster than before, and no longer slower than the Python codec.
- The native encoder picks the encoding by the value's type, as the Python
  codec does, not by the type's name: a user class named `Pid` or `int` is
  an object with no encoding of its own (`catch_all`, `__etf__` or the
  generic `(b'ClassName', {...})` form), and a subclass of `Pid`, `Atom`,
  ... encodes as that term. Encoding is 2-4 times faster for pids,
  references, integers and bignums.
- The native encoder writes binaries of 4 KiB or more straight into the
  result: a 1 MB binary encodes as fast as OTP does it (15 times faster
  than before on Linux, twice on Windows). A binary of 4 GiB or more raises
  `PyCodecError` instead of being written with a wrong length.
- The native decoder builds lists and tuples with less overhead: deeply
  nested and long lists decode up to twice as fast.
- Both decoders refuse a map whose keys are different in Erlang and equal
  in Python (`#{1 => a, 1.0 => b}`, `true` and `1`, `0.0` and `-0.0`, an
  atom and a string of the same text, tuples of these) with `PyCodecError`.
  Such a map used to decode to a dict with fewer entries, without an error.
- New decode option `"atom_cache"`: a list or tuple of atom texts that
  `ATOM_CACHE_REF` (tag 82) refers to, for terms that follow a distribution
  header. Without the option tag 82 raises `PyCodecError`.
  `term.codec` gains `binary_to_term_2` and `term_to_binary_2` for terms
  without the 131 header byte.
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
- New `term.Export(module, function, arity)` for `fun M:F/A`. Both codecs
  decode `EXPORT_EXT` and encode `Export` as OTP does; it used to raise
  `Unknown tag`. As in OTP 29, the arity may arrive in any integer encoding
  but must be a non-negative small integer, and module and function stay
  atoms whatever the atom options (`fun true:map/2` keeps `Atom('true')`).
  Error messages for a node name that is not an atom are unchanged.
- Local funs (`Fun`) encode as `NEW_FUN_EXT` in both codecs, with the right
  `Size`, so a fun from Erlang can be sent back and called there. Before,
  the Python codec sent a `(b'Fun', {...})` tuple and the native codec the
  same. Decoding ignores `Size` (as OTP does) and rejects what OTP rejects:
  a module that is not an atom, `OldIndex`/`OldUniq` that are not small
  integers, a creator that is not a pid, more than 255 free variables. Module,
  `OldIndex`, `OldUniq` and the pid no longer pass through the decode hooks
  or atom options; free variables are a `list` in both codecs (native gave a
  `tuple`). `Fun` has equality (the creator pid does not count, as in
  Erlang), hash and repr.
- Both codecs decode `FLOAT_EXT` (`term_to_binary(F, [{minor_version, 0}])`)
  and accept and reject its text as OTP 29 does; floats are still encoded only
  as `NEW_FLOAT_EXT`. A NaN or infinite `NEW_FLOAT_EXT` raises `PyCodecError`
  (both codecs returned `nan`).
- Atoms have at most 255 characters, as in OTP: longer ones raise
  `PyCodecError` on decoding and encoding, in both codecs, wherever they
  appear (node names, modules too). A Latin-1 atom tag may hold at most 255
  bytes, a UTF-8 one up to 1020. Both codecs used to accept up to 65535 bytes.
  An atom text that is not valid Unicode raises `PyCodecError` in the Python
  encoder (was `UnicodeEncodeError`).
- `LOCAL_EXT` (`term_to_binary(T, [local])`, OTP 26+) raises `PyCodecError`
  saying that only the node that encoded it can decode it, instead of
  `Unknown tag 121`.
- New `term.Record(module, name, exported, fields)` for OTP 29 native
  records (`RECORD_EXT`, EEP-79, experimental in OTP 29/30). Both codecs
  decode and encode it as OTP does: fields in definition order, flags 0 or 1
  (other bits reserved), no field named twice. Module, name and field names
  are always `Atom`; field values follow the decode options and hooks.
- Packaging: `pyproject.toml` is the only build configuration (`setup.py`,
  `build-wheels.sh` and the stale `requirements*.txt` are gone) and holds the
  one version; `Cargo.toml` carries it in semver form. Wheels are `abi3`:
  one per platform for every CPython >= 3.11. Without a Rust toolchain a
  source install now really falls back to the Python codec (the old fallback
  in `setup.py` never ran). License metadata is the SPDX `Apache-2.0`.
- CI: lint, type check and tests on Python 3.11-3.14 on Linux, Windows and
  macOS; OTP 25-29 judge the encoders; abi3 wheels for Linux (x86_64,
  aarch64), Windows and macOS (x86_64, arm64), each tested in a clean
  interpreter.
