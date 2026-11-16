"""Times the native and the Python codec on the benchmark workloads
(plan step TERM-21). A script, not a test; standard library only.

    python bench_codec.py WORKDIR SECONDS [--native PATH]

``WORKDIR`` has one directory per workload with its ``.etf`` files; one call
handles every file of the workload. ``SECONDS`` is the time budget per
workload, operation and codec. ``--native`` is the extension file of a
release build to load instead of ``term.native_codec_impl`` (which a
development install builds with the debug profile). Prints one JSON object
on stdout, laid out like ``bench_otp.erl``'s.
"""

import argparse
import gc
import importlib
import importlib.util
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from term import py_codec_impl

# A sample is a batch of calls that takes at least a tenth of the budget,
# within these bounds, so that the clock's resolution and the timing
# overhead do not show (as in bench_otp.erl).
MIN_BATCH_NS = 1_000_000
MAX_BATCH_NS = 20_000_000
# Bounds on the number of samples per measurement.
MIN_SAMPLES = 5
MAX_SAMPLES = 2000


def load_native(path: Path | None) -> ModuleType:
    """The native codec: the extension file at ``path``, else the installed
    one."""
    if path is None:
        return importlib.import_module("term.native_codec_impl")
    spec = importlib.util.spec_from_file_location("native_codec_impl", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load the native codec from %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _batch_ns(call: Callable[[], None], batch: int) -> int:
    t0 = time.perf_counter_ns()
    for _ in range(batch):
        call()
    return time.perf_counter_ns() - t0


def _calibrate(call: Callable[[], None], batch_ns: int) -> int:
    """The number of calls that fill ``batch_ns`` (also the warm-up)."""
    batch = 1
    while True:
        ns = _batch_ns(call, batch)
        if ns >= batch_ns:
            return batch
        if ns * 2 >= batch_ns:
            return batch * 2
        wanted = batch * batch_ns // max(ns, 1)
        batch = min(batch * 100, max(batch * 2, wanted))


def measure(call: Callable[[], None], budget_ns: int) -> list[float]:
    """Nanoseconds per call, one value per sample. The cyclic GC is off
    inside the timed loops and runs between measurements."""
    gc.collect()
    gc.disable()
    try:
        batch = _calibrate(call, max(MIN_BATCH_NS, min(MAX_BATCH_NS, budget_ns // 10)))
        _batch_ns(call, batch)
        deadline = time.perf_counter_ns() + budget_ns
        samples: list[float] = []
        while len(samples) < MAX_SAMPLES:
            samples.append(_batch_ns(call, batch) / batch)
            if len(samples) >= MIN_SAMPLES and time.perf_counter_ns() >= deadline:
                break
        return samples
    finally:
        gc.enable()


def percentile(ordered: list[float], p: int) -> float:
    """Nearest-rank percentile of a sorted list (as in bench_otp.erl)."""
    n = len(ordered)
    return ordered[max(1, min(n, (p * n + 99) // 100)) - 1]


def _result(
    workload: str, op: str, impl: str, nbytes: int, samples: list[float]
) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "workload": workload,
        "op": op,
        "impl": impl,
        "bytes": nbytes,
        "samples": len(ordered),
        "median_ns": round(percentile(ordered, 50), 1),
        "p95_ns": round(percentile(ordered, 95), 1),
    }


def bench_workload(
    directory: Path, impl: str, codec: ModuleType, budget_ns: int
) -> list[dict[str, Any]]:
    """Decode and encode results of one codec for one workload. Encoding
    starts from the values this codec decoded."""
    blobs = [p.read_bytes() for p in sorted(directory.glob("*.etf"))]
    b2t = codec.binary_to_term
    t2b = codec.term_to_binary
    values = [b2t(b, None)[0] for b in blobs]
    encoded = sum(len(t2b(v, None)) for v in values)

    def decode() -> None:
        for b in blobs:
            b2t(b, None)

    def encode() -> None:
        for v in values:
            t2b(v, None)

    name = directory.name
    return [
        _result(name, "decode", impl, sum(map(len, blobs)), measure(decode, budget_ns)),
        _result(name, "encode", impl, encoded, measure(encode, budget_ns)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workdir", type=Path)
    parser.add_argument("seconds", type=float)
    parser.add_argument("--native", type=Path, default=None)
    args = parser.parse_args()

    native = load_native(args.native)
    budget_ns = round(args.seconds * 1e9)
    results: list[dict[str, Any]] = []
    for directory in sorted(p for p in args.workdir.iterdir() if p.is_dir()):
        results += bench_workload(directory, "native", native, budget_ns)
        results += bench_workload(directory, "python", py_codec_impl, budget_ns)
    json.dump(
        {
            "impl": "python",
            "python": sys.version.split()[0],
            "native_module": str(native.__file__),
            "results": results,
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
