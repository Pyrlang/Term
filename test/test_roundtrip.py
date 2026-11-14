"""OTP judges what our codecs encode (plan step TERM-04).

For every fixture of both sets (``test/fixtures``, TERM-03, and
``test/fixtures/otp``, TERM-04), each codec decodes OTP's bytes and encodes
the value again. ``test/erl/check_roundtrip.erl`` then checks, in one ``erl``
run for the whole batch, that OTP decodes our bytes to exactly (``=:=``) the
term it decodes its own bytes to. Our bytes may differ from OTP's (the golden
byte comparison is ``test_fixtures.py:test_encode_fixture``); the term must
not.

Needs ``erl`` on ``PATH``; skipped otherwise.
"""

import importlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest
from fixture_manifest import (
    FIXTURE_DIR,
    OTP_VECTOR_DIR,
    REJECTED_FEATURE,
    Vector,
    codec_id,
    load_vectors,
    roundtrip_blocker,
)

from term import py_codec_impl

# The Erlang runtime used as the judge; None skips this module.
ERL = shutil.which("erl")

pytestmark = [
    pytest.mark.erlang,
    pytest.mark.skipif(ERL is None, reason="erl (Erlang/OTP) is not on PATH"),
]

CHECKER_SRC = Path(__file__).parent / "erl" / "check_roundtrip.erl"

# The fixture sets by name; the name is the first part of each test id.
SETS: dict[str, Path] = {"golden": FIXTURE_DIR, "otp": OTP_VECTOR_DIR}

# (set name, vector) for every vector that has a Python value: terms whose
# map keys Python cannot hash are rejected by design and have none.
CASES = [
    (set_name, v)
    for set_name, directory in SETS.items()
    for v in load_vectors(directory)
    if REJECTED_FEATURE not in v.features
]


# What the batch run found, keyed by (set name, codec id, vector name).
@dataclass
class _Report:
    # Decode or encode raised in Python: the exception text.
    errors: dict[tuple[str, str, str], str] = field(default_factory=dict)
    # OTP decoded our bytes to another term, or could not decode them.
    mismatches: dict[tuple[str, str, str], str] = field(default_factory=dict)
    # Files written and files OTP reported as checked, per (set, codec).
    written: dict[tuple[str, str], int] = field(default_factory=dict)
    checked: dict[tuple[str, str], int] = field(default_factory=dict)


def _codecs() -> list[ModuleType]:
    try:
        return [py_codec_impl, importlib.import_module("term.native_codec_impl")]
    except ImportError:
        return [py_codec_impl]


# Decode options under which every value encodes back to the same term:
# bitstrings as BitString (the default tuple would go out as a tuple).
DECODE_OPTIONS = {"bitstring": "BitString"}


def _reencode(codec: ModuleType, vector: Vector) -> bytes:
    value, tail = codec.binary_to_term(vector.path.read_bytes(), DECODE_OPTIONS)
    assert tail == b""
    encoded: bytes = codec.term_to_binary(value, None)
    return encoded


@pytest.fixture(scope="session")
def roundtrip_report(tmp_path_factory: pytest.TempPathFactory) -> _Report:
    """Re-encode every case with every codec, then run the checker once."""
    assert ERL is not None
    root = tmp_path_factory.mktemp("roundtrip")
    report = _Report()
    pairs: list[str] = []
    dir_keys: dict[str, tuple[str, str]] = {}
    for codec in _codecs():
        cid = codec_id(codec)
        for set_name, directory in SETS.items():
            out = root / ("%s-%s" % (set_name, cid))
            out.mkdir()
            written = 0
            for case_set, vector in CASES:
                if case_set != set_name:
                    continue
                try:
                    data = _reencode(codec, vector)
                except Exception as e:  # recorded; the case's test reports it
                    report.errors[(set_name, cid, vector.name)] = repr(e)
                    continue
                (out / (vector.name + ".etf")).write_bytes(data)
                written += 1
            report.written[(set_name, cid)] = written
            pairs += [directory.as_posix(), out.as_posix()]
            dir_keys[out.as_posix()] = (set_name, cid)

    beam_dir = root / "beam"
    beam_dir.mkdir()
    compile_expr = '{ok, _} = compile:file("%s", [{outdir, "%s"}, report]).' % (
        CHECKER_SRC.as_posix(),
        beam_dir.as_posix(),
    )
    cmd = [ERL, "-noshell", "-pa", beam_dir.as_posix(), "-eval", compile_expr]
    cmd += ["-run", "check_roundtrip", "main", *pairs]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if parts[0] == "checked" and len(parts) == 3:
            report.checked[dir_keys[parts[1]]] = int(parts[2])
        elif parts[0] == "mismatch" and len(parts) == 4:
            set_name, cid = dir_keys[parts[1]]
            report.mismatches[(set_name, cid, parts[2])] = parts[3]
    # Exit status 1 only means "mismatches found"; a checker that crashed or
    # never ran prints fewer "checked" lines than there are directories.
    assert proc.returncode in (0, 1) and len(report.checked) == len(
        dir_keys
    ), "check_roundtrip failed (exit %d):\n%s\n%s" % (
        proc.returncode,
        proc.stdout[-4000:],
        proc.stderr[-4000:],
    )
    return report


def test_checker_saw_every_file(roundtrip_report: _Report) -> None:
    """OTP checked each file the codecs wrote, in every directory."""
    assert roundtrip_report.checked == roundtrip_report.written


@pytest.mark.parametrize(
    "set_name,vector", CASES, ids=["%s/%s" % (s, v.name) for s, v in CASES]
)
def test_roundtrip(
    set_name: str,
    vector: Vector,
    codec: ModuleType,
    roundtrip_report: _Report,
    request: pytest.FixtureRequest,
) -> None:
    cid = codec_id(codec)
    step = roundtrip_blocker(vector, cid)
    if step is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=step))
    key = (set_name, cid, vector.name)
    assert key not in roundtrip_report.errors, roundtrip_report.errors.get(key)
    assert key not in roundtrip_report.mismatches, roundtrip_report.mismatches[key]
