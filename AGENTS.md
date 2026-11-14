# AGENTS.md — term-src (pyrlang-term)

Guidance for coding agents working on the native Rust codec in this
repository. Workspace-wide rules (plan tracking, commits, Python practices)
are in [../AGENTS.md](../AGENTS.md) and apply here too. In particular: no
`Co-Authored-By:` lines in commits, and plan steps for this repository are the
`TERM-*` steps in `../.agents/00-plan.md`.

## What this crate is

`native_codec_impl` is a `cdylib` Python extension that encodes and decodes
the Erlang External Term Format (ETF). It is an optional accelerator:

- `term/py_codec_impl.py` is the reference implementation and always works.
- `term/codec.py` imports the native module and falls back to Python.
- `pyrlang` feeds this codec bytes straight from the network.

| Path                    | Role                                               |
| ----------------------- | -------------------------------------------------- |
| `src/lib.rs`            | Module init, the four exported functions           |
| `src/decoder.rs`        | ETF bytes → Python objects                         |
| `src/encoder.rs`        | Python objects → ETF bytes                         |
| `src/reader.rs`         | Bounds-checked cursor over the input slice         |
| `src/consts.rs`         | ETF tag bytes                                      |
| `src/errors.rs`         | `CodecError` and its mapping to `PyCodecError`     |
| `term/*.py`             | Term classes (`Atom`, `Pid`, `Reference`, ...)     |
| `test/`                 | pytest suite run against both implementations      |

## Rules that are specific to this crate

### Parity with the Python codec

- The two implementations must be observably identical: same bytes out, same
  Python values in, same options, the same exception type (`PyCodecError`) for
  the same bad input.
- A feature or fix lands in both implementations in the same change, with one
  test body parametrized over both.
- Tag constants in `src/consts.rs` and `term/py_codec_impl.py` use the names
  from the OTP `erl_ext_dist` docs and stay in the same order in both files.

### Never panic, never abort

A panic that unwinds into CPython aborts the interpreter and takes the whole
Pyrlang node with it.

- No `unwrap()`, `expect()`, `panic!`, `unreachable!`, slice indexing or
  unchecked arithmetic on any path reachable from input data or from a Python
  call. Return `CodecError` and use `?`.
- Python calls fail routinely (unhashable dict key, a user hook raising, an
  import failing). Propagate the original Python exception; do not replace it
  with a generic one and do not discard it.
- `unwrap()` is acceptable only in tests.

### Input is hostile

- Read only through `Reader`. Every length field is checked against the bytes
  that remain before anything is allocated or read.
- Never pre-allocate from a length field alone. Cap `Vec::with_capacity` by
  what the remaining input could possibly contain.
- Decoding is recursive: enforce a nesting-depth limit and fail with
  `CodecError` instead of overflowing the native stack.
- Compressed terms: bound the decompressed size, stream into a growing buffer,
  and compare the final size with the declared one.
- Use checked or saturating arithmetic for sizes (`checked_mul`,
  `checked_add`); `term_len * 4` on a 32-bit target can wrap.

### `unsafe`

- The default is no `unsafe`. Do not use it for speed without a benchmark
  that shows it matters.
- Any `unsafe` block carries a `// SAFETY:` comment stating the invariant and
  why it holds. Never hand uninitialized memory to safe code
  (`Vec::set_len` before the bytes are written is not acceptable).

### Python binding layer

- The crate currently uses `rust-cpython` 0.7, which is unmaintained. Moving
  to PyO3 is a plan step (`TERM-02`). Until it lands, do not add code that
  deepens the `rust-cpython` dependency beyond what a step needs.
- Binding APIs change between releases. Read the documentation for the exact
  version pinned in `Cargo.toml` before using an API; do not write binding
  code from memory.
- Hold the GIL whenever a Python object is touched. Release it only around
  pure-Rust work on owned buffers, and only when a benchmark justifies it.
- Import Python classes once per call (or once per module) and cache them. Do
  not import inside the per-term path.
- Dispatch on Python type identity, not on the type's name string, for the
  term classes. A user class that happens to be named `Pid` is not a pid.
- Keep the exported surface small and stable: `binary_to_term`,
  `binary_to_term_2`, `term_to_binary`, `term_to_binary_2`, `PyCodecError`.
  Anything new is added to `py_codec_impl.py` under the same name.

### Errors

- One error enum (`CodecError`, `thiserror`). Variants carry the data needed
  for a useful message: the offending tag byte, the offset, expected and
  actual sizes.
- Every `CodecError` reaches Python as `PyCodecError`. Exceptions raised by
  user hooks pass through unchanged.
- Messages state what was found and where. They never include large slices of
  the input.

### Code style and tooling

- `cargo fmt` before every commit. `cargo clippy --all-targets -- -D warnings`
  must be clean; fix the code rather than adding `#[allow]`. Existing
  crate-wide `#![allow(...)]` attributes are to be removed, not extended.
- Stable Rust only. No nightly features. `Cargo.lock` stays committed.
- Keep dependencies few and maintained. A new dependency needs a reason in
  the commit message.
- Remove commented-out code instead of keeping it; git has the history.
- Prefer small typed helpers over repetition. The per-class `get_*_pyclass`
  functions are an example of what to fold into one helper.
- Pure-Rust logic (`Reader`, integer and atom encoding helpers) gets
  `#[cfg(test)]` unit tests that run with `cargo test` and need no Python.

### Performance

- Measure before optimizing. Keep a benchmark script next to the tests and
  quote before/after numbers in the commit message.
- The usual costs are Python calls per term, not byte copying: attribute
  lookups, imports, method calls such as `int.to_bytes`. Remove those first.
- Write output into one growing `Vec<u8>`. Do not build intermediate buffers
  per sub-term.

## Build and test

```sh
pip install -e .            # builds the extension through setuptools-rust
pytest test                 # runs every test against both implementations
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test                  # pure-Rust unit tests
```

- A test must not silently pass on the Python fallback when it claims to test
  the native module. Native tests skip with a visible reason if the extension
  is not built.
- Expected bytes in tests come from a real Erlang node (see the fixture
  generator introduced by `TERM-03`), not from our own encoder.
- Never commit compiled artifacts (`*.pyd`, `*.so`, `target/`, `dist/`).
- The crate version in `Cargo.toml` and the package version in
  `pyproject.toml` are bumped together.
