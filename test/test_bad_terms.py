"""Malformed input raises PyCodecError and nothing else (plan step TERM-05).

The contract for both decoders, on any input:

- the only exception ``binary_to_term`` raises is ``PyCodecError``;
- the process does not crash;
- memory stays below a fixed bound (see ``decode_worker.py``: a capped
  worker process for both codecs, ``tracemalloc`` for the Python codec).

Inputs:

- ``BAD_VECTORS``: byte sequences that OTP's own suites feed to
  ``binary_to_term`` and expect to fail (``binary_SUITE``: ``bad_terms``,
  ``more_bad_terms``, ``bad_binary_to_term``, ``bad_binary_to_term_2``,
  ``otp_5484``, ``otp_5933``, ``otp_6817``, ``otp_8117``, ``otp_8180``;
  ``node_container_SUITE:bad_nc``). Each must be rejected.
- Every fixture of both OTP-written sets (TERM-03, TERM-04), broken by the
  generators of ``etf_mutations.py``: truncated (must be rejected), a length
  field maxed out (must be rejected), and single bytes corrupted as OTP's
  ``corrupter`` does (may decode; must not raise anything else).

Not ported, because they test something other than decoding bytes:
``bad_binary_to_term`` with non-binary arguments and a bit-sized binary (a
Python caller passes ``bytes``), ``bad_size`` (``size/1`` of a fun), and the
``bad_nc`` cases about the local node's own pid/port limits or values that
``erts_test_utils`` refuses to encode in the first place.

Decoding runs in ``decode_worker.py``, so a native abort fails one test and
the run goes on. The ``erlang``-marked tests check that OTP 29 rejects every
input listed here as one that must be rejected.

Failing cases are strict xfails naming the plan step that fixes them; when
that step is done, delete its lines from the tables below.
"""

import json
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import IO, Any

import pytest
from etf_mutations import GENERATORS, MUST_REJECT, length_maxed, truncations, walk
from fixture_manifest import (
    FIXTURE_DIR,
    OTP_VECTOR_DIR,
    Vector,
    codec_id,
    load_vectors,
)

# OTP's data files for more_bad_terms and otp_8180, as raw bytes.
BAD_DIR = FIXTURE_DIR / "bad"

WORKER = Path(__file__).parent / "decode_worker.py"
CHECKER_SRC = Path(__file__).parent / "erl" / "check_rejected.erl"

# The Erlang runtime that judges which inputs are bad; None skips those tests.
ERL = shutil.which("erl")

# Longest time one worker request (all mutations of one fixture) may take.
REQUEST_TIMEOUT = 300.0


# One input that binary_to_term must reject.
@dataclass(frozen=True)
class BadVector:
    name: str  # <suite>.<case>.<what>, as in the fixture sets
    data: bytes


def _atom(text: str) -> bytes:
    """``ATOM_EXT`` of ASCII ``text``, as OTP's test helpers write it."""
    return b"d" + struct.pack(">H", len(text)) + text.encode()


def _u32(value: int) -> bytes:
    return struct.pack(">I", value & 0xFFFFFFFF)


def _bad_nc() -> Iterator[BadVector]:
    # From node_container_SUITE:bad_nc, through erts_test_utils:mk_ext_*:
    # remote node x@y with creation 2, and a creation that does not fit.
    x_y = _atom("x@y")
    yield BadVector(
        "ref_first_word_2p18",
        b"\x83r\x00\x03" + x_y + b"\x02" + _u32(1 << 18) + _u32(4711) + _u32(4711),
    )
    yield BadVector("ref_7_words", b"\x83Z\x00\x07" + x_y + _u32(2) + _u32(4711) * 7)
    yield BadVector("pid_creation_4", b"\x83g" + x_y + _u32(4711) + _u32(17) + b"\x04")
    yield BadVector("port_creation_4", b"\x83f" + x_y + _u32(4711) + b"\x04")
    yield BadVector(
        "ref_creation_4",
        b"\x83r\x00\x03" + x_y + b"\x04" + _u32(4711) + _u32(4711) + _u32(17),
    )


def _bad_binary_to_term() -> Iterator[BadVector]:
    # From binary_SUITE:bad_binary_to_term
    yield BadVector("float_nan", bytes([131, 70]) + b"\xff" * 8)
    # Truncated UTF-8 character (ERL-474)
    yield BadVector("atom_utf8_cut_char", bytes([131, 119, 1, 194, 163]))
    # Overlong 0-bit bitstring (should be encoded as 0-byte binary)
    yield BadVector("bits_0_of_0_bytes", bytes([131, 77, 0, 0, 0, 0, 0]))


def _bad_binary_to_term_2() -> Iterator[BadVector]:
    # From binary_SUITE:bad_binary_to_term_2 (OTP-4053)
    yield BadVector("large_big_huge", bytes([131, 111, 255, 255, 255, 0]))


def _bad_terms() -> Iterator[BadVector]:
    # From binary_SUITE:bad_terms; its corrupter is the "flip" generator.
    yield BadVector("bits_0", bytes([131, 77, 0, 0, 0, 3, 0, 11, 22, 33]))
    yield BadVector("bits_9", bytes([131, 77, 0, 0, 0, 3, 9, 11, 22, 33]))
    yield BadVector("bits_1_of_0_bytes", bytes([131, 77, 0, 0, 0, 0, 1, 11, 22, 33]))
    yield BadVector("bits_len_max", bytes([131, 77, 255, 255, 255, 255, 1, 11, 22, 33]))


def _more_bad_terms() -> Iterator[BadVector]:
    # From binary_SUITE:more_bad_terms (binary_SUITE_data/bad_binary)
    path = BAD_DIR / "binary_SUITE.more_bad_terms.bad_binary.etf"
    yield BadVector("bad_binary", path.read_bytes())


def _fake_fun(arity: int, env: list[int]) -> bytes:
    """binary_SUITE:fake_fun/2 for an environment of small integers."""
    uniq = bytes.fromhex("d41d8cd98f00b204e9800998ecf8427e")  # erlang:md5([])
    mod = b"binary_SUITE"
    # term_to_binary(self()) on a node that is not distributed.
    pid = b"X" + bytes([119, 13]) + b"nonode@nohost" + _u32(80) + _u32(0) + _u32(0)
    encoded_env = b"".join(bytes([97, n]) if n < 256 else b"b" + _u32(n) for n in env)
    body = bytes([arity]) + uniq + _u32(0) + _u32(len(env))
    body += b"d" + struct.pack(">H", len(mod)) + mod
    body += bytes([97, 0])  # OldIndex
    body += b"b" + _u32(0x123456)  # OldUniq
    body += pid + encoded_env
    return b"\x83p" + _u32(len(body) + 4) + body


def _otp_5484() -> Iterator[BadVector]:
    # From binary_SUITE:otp_5484
    node = b"wslin1427198@wslin14"
    yield BadVector(
        "pid_bad_values",
        bytes([131, 104, 2, 103, 100, 0, 20]) + node + b"\xff" * 9 + b"j",
    )
    yield BadVector(
        "pid_nil_node",
        bytes([131, 104, 2, 103, 106, 0, 0, 0, 17, 0, 0, 0, 135, 2, 106]),
    )
    # A old-type fun in a list containing a bad creator pid.
    yield BadVector(
        "old_fun_bad_pid",
        bytes(
            [131, 108, 0, 0, 0, 1, 117, 0, 0, 0, 0, 103, 100, 0, 13]
            + list(b"nonode@nohost")
            + [255, 255, 0, 25, 255, 0, 0, 0, 0, 100, 0, 1, 116, 97, 0, 98]
            + [6, 142, 121, 72, 106]
        ),
    )
    fun_head = [131, 108, 0, 0, 0, 1, 112]
    # A new-type fun in a list containing a bad creator pid.
    yield BadVector(
        "new_fun_bad_pid",
        bytes(
            fun_head
            + [0, 0, 0, 66, 0, 52, 216, 81, 158, 148, 250, 237, 109, 185, 9, 208]
            + [60, 202, 156, 244, 218, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0, 1, 116, 97]
            + [0, 98, 6, 142, 121, 72]
            + [103, 106]  # Pid with [] instead of an atom.
            + [0, 0, 0, 27, 0, 0, 0, 0, 0, 106]
        ),
    )
    fun_70 = [0, 0, 0, 70, 0, 224, 90, 4, 101, 48, 28, 110, 228, 153, 48, 239]
    fun_70 += [169, 232, 77, 108, 145, 0, 0, 0, 0, 0, 0, 0, 2]
    pid_tail = [103, 100, 0, 13] + list(b"nonode@nohost")
    pid_tail += [0, 0, 0, 48, 0, 0, 0, 0, 0, 97, 42, 97, 7, 106]
    # A new-type fun in a list containing a bad module.
    yield BadVector(
        "new_fun_bad_module",
        bytes(
            fun_head
            + fun_70
            + [107, 0, 1, 64]  # String instead of atom (same length).
            + [97, 0, 98, 6, 64, 82, 230]
            + pid_tail
        ),
    )
    # A new-type fun in a list containing a bad index.
    yield BadVector(
        "new_fun_bad_index",
        bytes(
            fun_head
            + fun_70
            + [100, 0, 1, 116]
            + [104, 0]  # Tuple {} instead of integer.
            + [98, 6, 64, 82, 230]
            + pid_tail
        ),
    )
    # A new-type fun in a list containing a bad unique value.
    yield BadVector(
        "new_fun_bad_uniq",
        bytes(
            fun_head
            + fun_70
            + [100, 0, 1, 116, 97, 0]
            + [100, 0, 2, 64, 65]  # Atom instead of integer.
            + pid_tail
        ),
    )
    # An absurdly large atom.
    yield BadVector("atom_65000", bytes([131, 100, 253, 232]) + b"*" * 65000)
    # Longer than 255 characters.
    yield BadVector("atom_256", bytes([131, 100, 1, 0]) + b"*" * 256)
    # OTP-7218: the error cases of external funs (EXPORT_EXT).
    yield BadVector("export_int_module", bytes([131, 113, 97, 13, 97, 13, 97, 13]))
    at = [100, 0, 1, 64]  # Atom: '@'
    yield BadVector("export_int_function", bytes([131, 113] + at + [97, 13, 97, 13]))
    yield BadVector("export_nil_arity", bytes([131, 113] + at + at + [106]))
    yield BadVector(
        "export_neg_arity", bytes([131, 113] + at + at + [98, 255, 255, 255, 255])
    )
    yield BadVector(
        "export_fun_arity", bytes([131, 113] + at + at + [113, 97, 13, 97, 13, 97, 13])
    )
    # Bad funs.
    yield BadVector("fake_fun_257_free", _fake_fun(0, list(range(257))))


def _otp_5933() -> Iterator[BadVector]:
    # From binary_SUITE:otp_5933: binary, bignum, huge bignum with lengths
    # 16#FFFFFFFF down to 16#FFFFFFF1 and nothing after them.
    for tag in b"mno":
        for length in range(0xFFFFFFFF, 0xFFFFFFF0, -1):
            yield BadVector(
                "%s_%X" % (chr(tag), length), bytes([131, tag]) + _u32(length)
            )


def _otp_6817() -> Iterator[BadVector]:
    # From binary_SUITE:otp_6817: FLOAT_EXT with garbage in the text.
    yield BadVector(
        "bad_float",
        bytes(
            [131, 99, 53, 46, 48, ord("X")]
            + [48] * 18
            + [101, 45, 48, 49, 0, 0, 0, 0, 0]
        ),
    )
    yield BadVector(
        "bin_and_float",
        bytes([131, 104, 2, 109, 0, 0, 1, 0])
        + bytes(range(256))
        + bytes([99, 51, 46, 49, 52])
        + b"Blurf"
        + bytes([48] * 8 + [49, 50, 52, 51, 52, 101, 43, 48, 48, 0, 0, 0, 0, 0]),
    )
    yield BadVector(
        "fun_and_float",
        bytes(
            [131, 104, 2, 112, 0, 0, 0, 66, 0, 238, 239, 135, 138, 137, 216, 89, 57]
            + [22, 111, 52, 126, 16, 84, 71, 8, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0, 1]
            + [116, 97, 0, 98, 5, 175, 169, 123, 103, 100, 0, 13]
            + list(b"nonode@nohost")
            + [0, 0, 0, 41, 0, 0, 0, 0, 0, 99, 50, 46, 55, 48, ord("Y")]
            + [57] * 13
            + [54, 52, 52, 55, 101, 43, 48, 48, 0, 0, 0, 0, 0]
        ),
    )
    yield BadVector(
        "ext_pid_and_float",
        bytes(
            [131, 108, 0, 0, 0, 1, 103, 100, 0, 13]
            + list(b"kalle@strider")
            + [0, 0, 0, 36, 0, 0, 0, 0, 2, 99, 48, 46, ord("@")]
            + [48] * 19
            + [101, 43, 48, 48, 0, 0, 0, 0, 0]
        ),
    )


def _otp_8117() -> Iterator[BadVector]:
    # From binary_SUITE:otp_8117: negative 32-bit counts. OTP's case encodes
    # fun() -> ok end and a named fun; here the two local-fun fixtures of the
    # golden set, which OTP 29 wrote the same way (NumFree at offset 27).
    funs = {
        "fun": (FIXTURE_DIR / "fun_local.etf").read_bytes(),
        "closure": (FIXTURE_DIR / "fun_closure.etf").read_bytes(),
    }
    for n in range(32):
        neg = _u32(-(1 << n))
        for what, fun in funs.items():
            yield BadVector(
                "%s_num_free_neg_2p%d" % (what, n), fun[:27] + neg + fun[31:]
            )
        yield BadVector(
            "list_len_neg_2p%d" % n,
            bytes([131, 104, 2, 108])
            + neg
            + bytes([97, 11, 104, 1, 97, 12, 97, 13, 106, 97, 14]),
        )
        yield BadVector(
            "tuple_arity_neg_2p%d" % n,
            bytes([131, 104, 2, 105]) + neg + bytes([97, 11, 97, 12, 97, 13, 97, 14]),
        )


def _otp_8180() -> Iterator[BadVector]:
    # From binary_SUITE:otp_8180 (binary_SUITE_data/zzz.terms.*)
    for path in sorted(BAD_DIR.glob("binary_SUITE.otp_8180.*.etf")):
        yield BadVector(path.stem.split(".otp_8180.")[1], path.read_bytes())


def _all_bad_vectors() -> list[BadVector]:
    sources = {
        "binary_SUITE.bad_terms": _bad_terms,
        "binary_SUITE.more_bad_terms": _more_bad_terms,
        "binary_SUITE.bad_binary_to_term": _bad_binary_to_term,
        "binary_SUITE.bad_binary_to_term_2": _bad_binary_to_term_2,
        "binary_SUITE.otp_5484": _otp_5484,
        "binary_SUITE.otp_5933": _otp_5933,
        "binary_SUITE.otp_6817": _otp_6817,
        "binary_SUITE.otp_8117": _otp_8117,
        "binary_SUITE.otp_8180": _otp_8180,
        "node_container_SUITE.bad_nc": _bad_nc,
    }
    return [
        BadVector("%s.%s" % (origin, v.name), v.data)
        for origin, make in sources.items()
        for v in make()
    ]


BAD_VECTORS = _all_bad_vectors()

# The fixture sets that the generators break; the name starts each test id.
SETS: dict[str, Path] = {"golden": FIXTURE_DIR, "otp": OTP_VECTOR_DIR}
FIXTURES: list[tuple[str, Vector]] = [
    (set_name, v) for set_name, d in SETS.items() for v in load_vectors(d)
]


# A worker process with a line reader, restarted after it dies.
class _Worker:
    def __init__(self) -> None:
        self.proc_: subprocess.Popen[str] | None = None
        self.lines_: queue.Queue[str | None] = queue.Queue()
        self.stderr_: IO[str] | None = None

    def _start(self) -> subprocess.Popen[str]:
        self.stderr_ = tempfile.TemporaryFile("w+", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_,
            text=True,
            encoding="utf-8",
        )
        self.lines_ = queue.Queue()
        lines = self.lines_
        stdout = proc.stdout
        assert stdout is not None

        def read() -> None:
            for line in stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        self.proc_ = proc
        return proc

    def _stderr_tail(self) -> str:
        if self.stderr_ is None:
            return ""
        self.stderr_.seek(0)
        return self.stderr_.read()[-2000:]

    def _died(self, what: str, at: str) -> dict[str, Any]:
        proc = self.proc_
        assert proc is not None
        proc.kill()
        code = proc.wait()
        self.proc_ = None
        error = "worker %s (exit code %s): %s" % (what, code, self._stderr_tail())
        return {"cases": None, "failure": {"case": at, "error": error}}

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send one request; return the reply, or a failure if the worker died."""
        proc = self.proc_ if self.proc_ is not None else self._start()
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        at = "before the first case"
        while True:
            try:
                line = self.lines_.get(timeout=REQUEST_TIMEOUT)
            except queue.Empty:
                return self._died("timed out after %ds" % REQUEST_TIMEOUT, at)
            if line is None:
                return self._died("died", at)
            reply: dict[str, Any] = json.loads(line)
            if "at" in reply:
                at = reply["at"]
                continue
            return reply

    def close(self) -> None:
        if self.proc_ is not None:
            assert self.proc_.stdin is not None
            self.proc_.stdin.close()
            try:
                self.proc_.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc_.kill()
                self.proc_.wait()
            self.proc_ = None


@pytest.fixture(scope="session")
def worker() -> Iterator[_Worker]:
    """A decode worker shared by all tests; restarted when a case kills it."""
    w = _Worker()
    yield w
    w.close()


def _assert_reply(reply: dict[str, Any]) -> None:
    failure = reply["failure"]
    assert failure is None, "%s: %s" % (failure["case"], failure["error"])


@pytest.mark.parametrize("vector", BAD_VECTORS, ids=[v.name for v in BAD_VECTORS])
def test_bad_vector(
    vector: BadVector,
    codec: ModuleType,
    worker: _Worker,
    request: pytest.FixtureRequest,
) -> None:
    """OTP rejects this input; so must we, with PyCodecError."""
    cid = codec_id(codec)
    step = bad_vector_blocker(vector.name, cid)
    if step is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=step))
    _assert_reply(worker.run({"codec": cid, "gen": "reject", "hex": vector.data.hex()}))


# Failing fixtures quoted in one test's failure message.
_QUOTE_LIMIT = 20


@pytest.mark.parametrize("set_name", list(SETS))
@pytest.mark.parametrize("gen", list(GENERATORS))
def test_broken_fixtures(
    gen: str,
    set_name: str,
    codec: ModuleType,
    worker: _Worker,
    request: pytest.FixtureRequest,
) -> None:
    """Every mutation of every fixture of the set raises PyCodecError (or,
    for ``flip``, may decode); nothing else is raised, no process dies.

    One test per (generator, set, codec), not per fixture: which mutation
    fails first depends on the bytes, not on a feature a table could name.
    The message lists the failing fixtures.
    """
    cid = codec_id(codec)
    step = MUTATIONS_BLOCKED.get((gen, cid))
    if step is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=step))
    failures = []
    for s, v in FIXTURES:
        if s != set_name:
            continue
        reply = worker.run({"codec": cid, "gen": gen, "path": str(v.path)})
        failure = reply["failure"]
        if failure is not None:
            failures.append("%s: %s: %s" % (v.name, failure["case"], failure["error"]))
    assert not failures, "%d fixtures fail:\n%s" % (
        len(failures),
        "\n".join(f[:300] for f in failures[:_QUOTE_LIMIT]),
    )


# ---------------------------------------------------------------------------
# OTP as the judge of "must reject"

# Truncation offsets per fixture sent to OTP: OTP only confirms that cut
# terms are bad, so a small sample is enough.
_OTP_TRUNCATE_BUDGET = 16


def _must_reject_inputs() -> list[tuple[str, bytes]]:
    """Every input that the tests above require to be rejected."""
    inputs = [(v.name, v.data) for v in BAD_VECTORS]
    for set_name, v in FIXTURES:
        data = v.path.read_bytes()
        where = "%s/%s" % (set_name, v.name)
        for label, bad in length_maxed(data):
            inputs.append(("%s: %s" % (where, label), bad))
        for label, bad in truncations(data, _OTP_TRUNCATE_BUDGET):
            inputs.append(("%s: %s" % (where, label), bad))
    return inputs


@pytest.mark.erlang
@pytest.mark.skipif(ERL is None, reason="erl (Erlang/OTP) is not on PATH")
def test_otp_rejects_them_too(tmp_path: Path) -> None:
    """OTP's binary_to_term/1 rejects every input we must reject."""
    assert ERL is not None
    inputs = _must_reject_inputs()
    blob = tmp_path / "inputs.bin"
    blob.write_bytes(b"".join(_u32(len(d)) + d for _, d in inputs))
    beam_dir = tmp_path / "beam"
    beam_dir.mkdir()
    compile_expr = '{ok, _} = compile:file("%s", [{outdir, "%s"}, report]).' % (
        CHECKER_SRC.as_posix(),
        beam_dir.as_posix(),
    )
    cmd = [ERL, "-noshell", "-pa", beam_dir.as_posix(), "-eval", compile_expr]
    cmd += ["-run", "check_rejected", "main", blob.as_posix()]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    accepted = []
    checked = None
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if parts[0] == "accepted":
            accepted.append("%s -> %s" % (inputs[int(parts[1])][0], parts[2]))
        elif parts[0] == "checked":
            checked = int(parts[1])
    assert checked == len(inputs), "check_rejected failed:\n%s\n%s" % (
        proc.stdout[-4000:],
        proc.stderr[-4000:],
    )
    assert not accepted, "OTP decodes %d of them:\n%s" % (
        len(accepted),
        "\n".join(accepted[:50]),
    )


def test_walker_reads_every_fixture() -> None:
    """``walk`` understands every fixture (else ``length`` mutates nothing)."""
    for _set_name, v in FIXTURES:
        walk(v.path.read_bytes())


# ---------------------------------------------------------------------------
# Expected failures: the plan step that fixes them. Delete a step's lines
# when it is done; strict xfails show any line that is wrong.

# (generator, codec id) -> plan steps, for test_broken_fixtures.
MUTATIONS_BLOCKED: dict[tuple[str, str], str] = {
    # Python: IndexError, struct.error, TypeError, UnicodeDecodeError, short
    # reads that "succeed" (no bounds checks). Both: a compressed term whose
    # zlib checksum is cut off still decodes.
    ("truncate", "py"): "TERM-08, TERM-09",
    ("truncate", "native"): "TERM-09",
    ("length", "py"): "TERM-08",
    # Vec::with_capacity / vec![0; n] from the length field: the process
    # aborts ("memory allocation of 34359738360 bytes failed").
    ("length", "native"): "TERM-09",
    ("flip", "py"): "TERM-08",
    ("flip", "native"): "TERM-09",
}


def _vector_blocks() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    both: dict[str, str] = {}
    by: dict[tuple[str, str], str] = {}
    b = "binary_SUITE."
    # Bits must be 1..8, and 0 bytes carry no bits.
    for n in ("bad_terms.bits_0", "bad_terms.bits_9", "bad_terms.bits_1_of_0_bytes"):
        both[b + n] = "TERM-20"
    both[b + "bad_binary_to_term.bits_0_of_0_bytes"] = "TERM-20"
    # NEW_FLOAT_EXT must be finite.
    both[b + "bad_binary_to_term.float_nan"] = "TERM-14"
    # Atoms have at most 255 characters.
    both[b + "otp_5484.atom_65000"] = "TERM-15"
    both[b + "otp_5484.atom_256"] = "TERM-15"
    # Fun fields of the wrong type; more free variables than MAX_ARG (255).
    for n in ("bad_module", "bad_index", "bad_uniq"):
        both[b + "otp_5484.new_fun_" + n] = "TERM-13"
    both[b + "otp_5484.fake_fun_257_free"] = "TERM-13"
    # Node container values out of range for their tag.
    both[b + "otp_5484.pid_bad_values"] = "TERM-11"
    for n in ("ref_first_word_2p18", "ref_7_words", "pid_creation_4", "ref_creation_4"):
        both["node_container_SUITE.bad_nc." + n] = "TERM-11"
    # A node that is not an atom (Python: AssertionError; native accepts).
    both[b + "otp_5484.pid_nil_node"] = "TERM-08"
    both[b + "otp_5484.new_fun_bad_pid"] = "TERM-08"
    # Python reads past the end: IndexError, UnicodeDecodeError, short reads.
    by[(b + "bad_binary_to_term.atom_utf8_cut_char", "py")] = "TERM-08"
    by[(b + "bad_binary_to_term_2.large_big_huge", "py")] = "TERM-08"
    for length in range(0xFFFFFFFF, 0xFFFFFFF0, -1):
        by[(b + "otp_5933.n_%X" % length, "py")] = "TERM-08"
        by[(b + "otp_5933.o_%X" % length, "py")] = "TERM-08"
    for bit in range(32):
        for what in ("fun_num_free", "closure_num_free"):
            by[(b + "otp_8117.%s_neg_2p%d" % (what, bit), "py")] = "TERM-08"
        for what in ("list_len", "tuple_arity"):
            by[(b + "otp_8117.%s_neg_2p%d" % (what, bit), "py")] = "TERM-08"
            # Native pre-allocates 2^31.. elements and aborts.
            by[(b + "otp_8117.%s_neg_2p%d" % (what, bit), "native")] = "TERM-09"
    for n in ("2224", "24619", "25681"):
        by[(b + "otp_8180.zzz.terms." + n, "py")] = "TERM-08"
    for n in ("1197", "2224", "24619", "25681", "26563", "26744", "527"):
        by[(b + "otp_8180.zzz.terms." + n, "native")] = "TERM-09"
    return both, by


# Vector name -> step for both codecs; (vector name, codec id) -> step.
VECTOR_BLOCKED, VECTOR_BLOCKED_BY = _vector_blocks()


def bad_vector_blocker(name: str, cid: str) -> str | None:
    """The plan steps that must land before ``cid`` rejects vector ``name``."""
    steps = {VECTOR_BLOCKED.get(name), VECTOR_BLOCKED_BY.get((name, cid))}
    return ", ".join(sorted(s for s in steps if s)) or None


def test_blocked_names_exist() -> None:
    """The tables above name only vectors that exist."""
    names = {v.name for v in BAD_VECTORS}
    assert set(VECTOR_BLOCKED) <= names
    assert {n for n, _ in VECTOR_BLOCKED_BY} <= names
