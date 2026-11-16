"""Smoke test of the benchmark scripts (plan step TERM-21): they finish and
emit valid results. No timing is asserted. Deselected unless ``-m bench``."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from otp import ERL

RUN = Path(__file__).parent / "bench" / "run.py"


@pytest.mark.bench
def test_benchmark_runs(tmp_path: Path) -> None:
    if ERL is None:
        pytest.skip("no erl: set PYRLANG_ERL or put Erlang/OTP on PATH")
    if shutil.which("cargo") is None:
        pytest.skip("no cargo: the benchmark builds the native codec itself")
    raw = tmp_path / "raw.json"
    proc = subprocess.run(
        [sys.executable, str(RUN), "--seconds", "0.01", "--json", str(raw)],
        capture_output=True,
        text=True,
        timeout=1800,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr
    results = json.loads(raw.read_text(encoding="utf-8"))
    otp = {(r["workload"], r["op"]) for r in results["otp"]["results"]}
    for impl in ("native", "python"):
        ours = {
            (r["workload"], r["op"])
            for r in results["codecs"]["results"]
            if r["impl"] == impl
        }
        assert ours == otp and len(otp) >= 20
    every = results["otp"]["results"] + results["codecs"]["results"]
    assert all(r["median_ns"] > 0 and r["samples"] >= 5 for r in every)
    # The table has a row per workload and operation.
    assert proc.stdout.count("| decode |") == len(otp) // 2
