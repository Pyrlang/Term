# Known differences

Where this codec knowingly behaves differently from OTP 29's
`binary_to_term`/`term_to_binary`, or the Python and native codecs differ
from each other. One bullet each: what, an example, why. Remove a bullet
when the difference is gone.

## From OTP 29

- **Resource limits.** Decoding and encoding refuse nesting deeper than
  `max_depth` (4096); a compressed term may declare at most `max_size`
  (256 MiB). OTP has no such limits. Example: 4097 nested lists,
  `<<131, (<<108,0,0,0,1>>)*4097, 106*4098>>` → `PyCodecError`. Why: input
  comes from the network (TERM-09, TERM-22).
- **References with no ID words are rejected.** OTP 29 reads the first word
  from past the end of the term, so it accepts or rejects depending on the
  bytes that follow. Example: `<<131,90,0,0,119,3,"a@b",0,0,0,1>>`
  (`NEWER_REFERENCE_EXT`), `<<131,114,0,0,119,3,"a@b",1>>`
  (`NEW_REFERENCE_EXT`) → `PyCodecError` (TERM-11).
- **`FLOAT_EXT` needs a NUL inside its 31 bytes.** OTP reads past the term
  to find one. Example: `<<131,99,"1.",$0*29>>` → `PyCodecError` (TERM-14).
- **`LOCAL_EXT` is never decoded.** OTP decodes it on the node that wrote
  it. Example: `term_to_binary({a,1}, [local])` → `PyCodecError` naming
  `LOCAL_EXT` (TERM-16).
- **`ATOM_CACHE_REF` (82) is decoded wherever an atom may stand,** given
  the decode option `atom_cache`. OTP accepts it only in terms that follow
  a distribution header. Example: `binary_to_term(<<131,82,0>>,
  {"atom_cache": ["a"]})` → `Atom("a")`; without the option →
  `PyCodecError`, as OTP's `badarg` (TERM-18).
- **Map keys Python cannot hash are rejected.** Example: `#{[a] => 1}` →
  `PyCodecError` ("Map key of type list is not hashable").
- **Map keys that are equal in Python are merged, silently.** Erlang's `1`,
  `1.0` and `true` are three keys; in Python `1 == 1.0 == True`. Example:
  `#{1 => a, 1.0 => b, true => c}`
  (`<<131,116,0,0,0,3,97,1,119,1,97,70,63,240,0,0,0,0,0,0,119,1,98,119,4,116,114,117,101,119,1,99>>`)
  → `{1: Atom('c')}` in both codecs. The same for `0`, `0.0`, `-0.0`,
  `false` and keys containing them (`{1}` and `{1.0}`). Why: Python dict
  semantics; plan step TERM-23 makes the decoders refuse such maps.
- **Some values change type on the way through Python.** `true`, `false`,
  `undefined` ↔ `True`, `False`, `None`; `"abc"` (`STRING_EXT`) → `str`, but
  `[97,256,98]` → `list`, `"aĀb"` encodes as that list; `[]` and `""` both
  encode as `NIL_EXT` and decode as `[]`. The bytes re-encode the same; the
  Python types differ.
- **Bitstrings decode to `(bytes, bits)` by default**, which encodes back as a
  tuple, not a bitstring. Example: `<<5:7>>` → `(b"\n", 7)`; pass
  `{"bitstring": "BitString"}` to get a value that round-trips (TERM-20).
- **Funs keep their creator pid.** OTP 23+ drops it on decoding and writes a
  dummy one; we decode it and send it back unchanged. `Fun.__eq__` ignores
  it, as Erlang's `=:=` does (TERM-13).
- **We encode only OTP 29's default output.** Never `FLOAT_EXT`,
  `ATOM_EXT`/`SMALL_ATOM_EXT`, `NEW_PORT_EXT`/`PORT_EXT`, `REFERENCE_EXT`,
  compressed terms or any `term_to_binary` option. Example: a port decoded
  from `NEW_PORT_EXT` re-encodes as `V4_PORT_EXT`, as OTP 29 does.
- **Records are sent to any peer.** OTP before 29 cannot decode
  `RECORD_EXT`; encoding a `Record` for such a peer gives bytes it rejects
  (TERM-17).
- **Older OTP releases disagree on one bad input; we follow OTP 29.**
  `<<131,77,0,0,0,0,0>>` (0 bits in 0 bytes): OTP 25/26 decode `<<>>`, OTP 27
  and 29 reject it, OTP 28.4.1 aborts the VM; we reject it.

## Python codec vs native codec

- **Encode hook exceptions.** Python lets an exception from `encode_hook`,
  `catch_all` or `__etf__` escape unchanged; native raises `PyCodecError`
  with it as `__cause__`. Example: `term_to_binary(object(),
  {"encode_hook": {"catch_all": f}})` with `f` raising `ValueError`.
- **Type dispatch.** Native picks the encoding by the type's `__name__`,
  Python by `isinstance`. Example: a user class named `Pid` is encoded as a
  pid by native, as a generic object by Python (plan section 2.2).
