Malformed terms from Erlang/OTP's `erts/emulator/test/binary_SUITE_data`
(branch `maint-29`), used by `test/test_bad_terms.py`:

- `binary_SUITE.more_bad_terms.bad_binary.etf`: the file `bad_binary`, as is.
- `binary_SUITE.otp_8180.zzz.terms.<N>.etf`: the binary in `zzz.terms.<N>`
  (Erlang term text `<<...>>.`), written out as raw bytes.

Copyright Ericsson AB; licensed under the Apache License, Version 2.0.
