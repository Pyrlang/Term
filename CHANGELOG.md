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
