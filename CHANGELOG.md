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
