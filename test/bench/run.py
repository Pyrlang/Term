"""Codec benchmark driver (plan step TERM-21): OTP's C BIFs against the
native (Rust) codec and the Python codec. Standard library only.

    python test/bench/run.py [--seconds S] [--cpu N] [--out FILE] [--json FILE]

Steps: OTP writes the workloads (``gen_workloads.erl``, plus the fixture
corpora of ``test/fixtures``); cargo builds the extension with the release
profile into ``test/bench/_work`` (the development install is a debug build
and is left alone); ``bench_otp.erl`` and ``bench_codec.py`` time them; the
results are printed as one Markdown table.

The comparison is not like for like: OTP builds terms on a process heap
with no foreign-function calls, our codecs build CPython objects. It tells
how far we are from OTP, not which implementation is better written.

The ``erl`` used is ``$PYRLANG_ERL`` or the one on ``PATH``. On a CPU with
performance and efficiency cores, pass ``--cpu`` with the number of a
performance core: a benchmark that the OS moves to an efficiency core runs
at half the speed.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# This directory, the repository root, and the scratch directory (gitignored).
BENCH_DIR = Path(__file__).resolve().parent
REPO_DIR = BENCH_DIR.parent.parent
WORK_DIR = BENCH_DIR / "_work"
FIXTURE_DIR = REPO_DIR / "test" / "fixtures"

# Fixture features with no Python value: both codecs refuse those terms
# (REJECTED_FEATURES in test/fixture_manifest.py).
REJECTED_FEATURES = frozenset({"unhashable_key", "colliding_keys", "local_ext"})

# The fixture corpora timed as one workload each: name -> directory.
CORPORA = {"fixtures_golden": FIXTURE_DIR, "fixtures_otp": FIXTURE_DIR / "otp"}


def _run(cmd: list[str], **kwargs: Any) -> str:
    """Run a command, return its stdout; its stderr goes to ours."""
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, **kwargs
    )
    if proc.returncode != 0:
        raise SystemExit("%s failed with status %d" % (cmd[0], proc.returncode))
    return str(proc.stdout)


def find_erl() -> str:
    """The erl to benchmark: ``$PYRLANG_ERL`` or the one on ``PATH``."""
    erl = os.environ.get("PYRLANG_ERL") or shutil.which("erl")
    if erl is None:
        raise SystemExit("no erl: set PYRLANG_ERL or put Erlang/OTP on PATH")
    return erl


def compile_erlang(erl: str) -> Path:
    """Compile the two Erlang modules with the erlc next to ``erl``."""
    ebin = WORK_DIR / ("ebin-" + sys.platform)
    ebin.mkdir(parents=True, exist_ok=True)
    erlc = shutil.which("erlc", path=str(Path(erl).parent)) or shutil.which("erlc")
    if erlc is None:
        raise SystemExit("no erlc next to %s or on PATH" % erl)
    sources = [str(BENCH_DIR / "gen_workloads.erl"), str(BENCH_DIR / "bench_otp.erl")]
    _run([erlc, "-o", str(ebin)] + sources)
    return ebin


def write_workloads(erl: str, ebin: Path) -> Path:
    """Fill the workload directory: OTP's shaped terms and the corpora."""
    workloads = WORK_DIR / ("workloads-" + sys.platform)
    shutil.rmtree(workloads, ignore_errors=True)
    workloads.mkdir(parents=True)
    _run(
        [erl, "-noshell", "-pa", str(ebin), "-run", "gen_workloads", "main"]
        + [str(workloads), "-s", "init", "stop"],
        stderr=subprocess.DEVNULL,
    )
    for name, source in CORPORA.items():
        target = workloads / name
        target.mkdir()
        lines = (source / "MANIFEST.tsv").read_text(encoding="utf-8").splitlines()
        header = lines[0].split("\t")
        for line in lines[1:]:
            row = dict(zip(header, line.split("\t"), strict=True))
            if not REJECTED_FEATURES & set(row["features"].split(",")):
                shutil.copy(source / (row["name"] + ".etf"), target)
    return workloads


def build_native() -> Path:
    """Build the extension with the release profile; return a copy that
    Python can import by path."""
    target = WORK_DIR / ("target-" + sys.platform)
    env = dict(os.environ, CARGO_TARGET_DIR=str(target), PYO3_PYTHON=sys.executable)
    _run(["cargo", "build", "--release", "--quiet"], cwd=REPO_DIR, env=env)
    if sys.platform == "win32":
        built, suffix = "native_codec_impl.dll", ".pyd"
    elif sys.platform == "darwin":
        built, suffix = "libnative_codec_impl.dylib", ".abi3.so"
    else:
        built, suffix = "libnative_codec_impl.so", ".abi3.so"
    module = WORK_DIR / ("native-" + sys.platform) / ("native_codec_impl" + suffix)
    module.parent.mkdir(exist_ok=True)
    shutil.copy(target / "release" / built, module)
    return module


def pin_cpu(cpu: int) -> None:
    """Keep this process, and the benchmark processes it starts, on one
    logical CPU."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        if not kernel32.SetProcessAffinityMask(kernel32.GetCurrentProcess(), 1 << cpu):
            raise SystemExit("cannot pin to CPU %d: %s" % (cpu, ctypes.WinError()))
    elif hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {cpu})
    else:
        raise SystemExit("--cpu is not supported on %s" % sys.platform)


def cpu_name() -> str:
    """The processor's marketing name, as far as the OS tells."""
    if sys.platform == "win32":
        import winreg

        key = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            return str(winreg.QueryValueEx(handle, "ProcessorNameString")[0]).strip()
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _num(x: float) -> str:
    """A number with about three significant digits and no exponent."""
    if x >= 100:
        return "%.0f" % x
    if x >= 10:
        return "%.1f" % x
    if x >= 1:
        return "%.2f" % x
    return "%.3f" % x


def _us(ns: float) -> str:
    """Nanoseconds as microseconds."""
    return _num(ns / 1000.0)


def _ratio(a: float, b: float) -> str:
    return _num(a / b) if b else "-"


def table(
    otp: dict[str, Any], codecs: dict[str, Any], seconds: float, cpu: int | None
) -> str:
    """The Markdown report: environment header and one row per workload
    and operation."""
    by_key: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for r in otp["results"]:
        by_key.setdefault((r["workload"], r["op"]), {})["otp"] = r
    for r in codecs["results"]:
        by_key.setdefault((r["workload"], r["op"]), {})[r["impl"]] = r

    rustc = _run(["rustc", "--version"], cwd=REPO_DIR).strip()
    out = [
        "Codec benchmark (TERM-21). Times are microseconds per call, median"
        " / p95; one call handles the whole workload.",
        "",
        "- Native build: cargo `release` profile, %s" % rustc,
        "- Python %s (%s)" % (codecs["python"], platform.python_implementation()),
        "- Erlang/OTP %s, erts %s, `+S 1`" % (otp["otp_release"], otp["erts"]),
        "- CPU: %s%s"
        % (cpu_name(), "" if cpu is None else ", pinned to logical CPU %d" % cpu),
        "- OS: %s" % platform.platform(),
        "- Budget: %g s per workload, operation and codec" % seconds,
        "",
        "| workload | op | bytes | OTP | native | Python | native MB/s"
        " | native/OTP | Python/native |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (workload, op), impls in sorted(by_key.items()):
        o, n, p = impls["otp"], impls["native"], impls["python"]
        mb_s = n["bytes"] / (n["median_ns"] / 1e9) / 1e6
        out.append(
            "| %s | %s | %d | %s / %s | %s / %s | %s / %s | %s | %s | %s |"
            % (
                workload,
                op,
                n["bytes"],
                _us(o["median_ns"]),
                _us(o["p95_ns"]),
                _us(n["median_ns"]),
                _us(n["p95_ns"]),
                _us(p["median_ns"]),
                _us(p["p95_ns"]),
                _num(mb_s),
                _ratio(n["median_ns"], o["median_ns"]),
                _ratio(p["median_ns"], n["median_ns"]),
            )
        )
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--seconds",
        type=float,
        default=1.0,
        help="time budget per workload, operation and codec (default 1.0)",
    )
    parser.add_argument(
        "--cpu", type=int, help="pin the benchmark processes to this logical CPU"
    )
    parser.add_argument("--out", type=Path, help="also write the table to this file")
    parser.add_argument("--json", type=Path, help="write the raw results to this file")
    args = parser.parse_args()

    erl = find_erl()
    ebin = compile_erlang(erl)
    workloads = write_workloads(erl, ebin)
    native = build_native()
    if args.cpu is not None:
        pin_cpu(args.cpu)

    otp = json.loads(
        _run(
            [erl, "+S", "1", "-noshell", "-pa", str(ebin), "-run", "bench_otp", "main"]
            + [str(workloads), repr(args.seconds), "-s", "init", "stop"]
        )
    )
    codecs = json.loads(
        _run(
            [sys.executable, str(BENCH_DIR / "bench_codec.py"), str(workloads)]
            + [repr(args.seconds), "--native", str(native)]
        )
    )
    report = table(otp, codecs, args.seconds, args.cpu)
    sys.stdout.write(report)
    if args.out is not None:
        args.out.write_text(report, encoding="utf-8", newline="\n")
    if args.json is not None:
        raw = {"otp": otp, "codecs": codecs}
        args.json.write_text(json.dumps(raw, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
