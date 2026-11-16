"""Subprocess that decodes hostile input for ``test_bad_terms.py`` (TERM-05).

The native codec can abort the interpreter on hostile input (a failed
allocation sized from a length field aborts the process). The tests therefore
decode in this worker, never in the pytest process: a crash costs one test,
not the run.

The worker caps its own memory before decoding anything (a Windows job
object, ``RLIMIT_AS`` elsewhere), ``MEMORY_HEADROOM`` above what it uses at
start. An allocation beyond the cap fails: ``MemoryError`` in the Python
codec, an abort in the native one. The Python codec additionally runs under
``tracemalloc`` for the ``length`` generator, whose mutations ask for up to
4 GiB, and its peak per case must stay below ``PY_PEAK_LIMIT``.

Protocol: one JSON request per stdin line, one JSON reply per stdout line.

- request ``{"codec": "py"|"native", "gen": <etf_mutations.GENERATORS key>,
  "path": <file>}``: run every mutation of the file's bytes;
- request ``{"codec": ..., "gen": "reject", "hex": <bytes>}``: decode the
  bytes once, unmutated;
- before each native case, ``{"at": <label>}`` names it, so that the parent
  can tell which case crashed;
- reply ``{"cases": N, "failure": null | {"case": <label>, "error": <text>}}``.
  Decoding stops at the first failure.
"""

import json
import os
import sys
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

from etf_mutations import GENERATORS, MUST_REJECT

from term import py_codec_impl

# Memory the worker may allocate on top of what it uses at start.
MEMORY_HEADROOM = 256 * 1024 * 1024

# Largest tracemalloc peak one Python-codec decode may reach.
PY_PEAK_LIMIT = 16 * 1024 * 1024

# Longest repr of a wrongly decoded value quoted in a failure.
_REPR_LIMIT = 200


def _limit_memory_windows(headroom: int) -> None:
    if sys.platform != "win32":  # lets mypy check this on POSIX too
        raise NotImplementedError("Windows only")
    import ctypes
    from ctypes import wintypes

    # Layouts from winnt.h: JOBOBJECT_EXTENDED_LIMIT_INFORMATION and parts.
    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    job_object_extended_limit_information = 9
    job_object_limit_process_memory = 0x100

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(MemoryCounters),
        wintypes.DWORD,
    ]

    me = kernel32.GetCurrentProcess()
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(MemoryCounters)
    if not psapi.GetProcessMemoryInfo(me, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())

    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = job_object_limit_process_memory
    # The job limit counts committed private memory (PagefileUsage).
    limits.ProcessMemoryLimit = counters.PagefileUsage + headroom
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    ok = kernel32.SetInformationJobObject(
        job,
        job_object_extended_limit_information,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    if not ok or not kernel32.AssignProcessToJobObject(job, me):
        raise ctypes.WinError(ctypes.get_last_error())


def _limit_memory_posix(headroom: int) -> None:
    if sys.platform == "win32":  # lets mypy check this on Windows too
        raise NotImplementedError("POSIX only")
    import resource

    # Address space in use now; Linux reports it in /proc, others get a
    # generous fixed base.
    try:
        pages = int(Path("/proc/self/statm").read_text().split()[0])
        in_use = pages * os.sysconf("SC_PAGE_SIZE")
    except OSError:
        in_use = 2 * 1024 * 1024 * 1024
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    soft = in_use + headroom
    if hard != resource.RLIM_INFINITY:
        soft = min(soft, hard)
    resource.setrlimit(resource.RLIMIT_AS, (soft, hard))


def limit_memory(headroom: int) -> None:
    """Cap this process at its current memory use plus ``headroom`` bytes."""
    if sys.platform == "win32":
        _limit_memory_windows(headroom)
    else:
        _limit_memory_posix(headroom)


def _load_codec(cid: str) -> ModuleType:
    if cid == "py":
        return py_codec_impl
    from term import native_codec_impl

    return native_codec_impl


def _cases(request: dict[str, Any]) -> Iterator[tuple[str, bytes]]:
    if request["gen"] == "reject":
        yield "as given", bytes.fromhex(request["hex"])
        return
    yield from GENERATORS[request["gen"]](Path(request["path"]).read_bytes())


def _short_repr(value: object) -> str:
    try:
        text = repr(value)
    except ValueError:  # an int too long for str() (sys.int_info limit)
        return "<%s too long to print>" % type(value).__name__
    if len(text) > _REPR_LIMIT:
        text = text[:_REPR_LIMIT] + "..."
    return text


def _check(
    codec: ModuleType, data: bytes, must_reject: bool, trace: bool
) -> str | None:
    """Decode ``data``; return what went wrong, or None."""
    if trace:
        tracemalloc.reset_peak()
    try:
        value, _tail = codec.binary_to_term(data, None)
    except codec.PyCodecError:
        outcome = None
    except Exception as e:  # the contract allows PyCodecError only
        outcome = "%s: %s" % (type(e).__name__, e)
    else:
        outcome = "decoded to %s" % _short_repr(value) if must_reject else None
    if trace:
        _current, peak = tracemalloc.get_traced_memory()
        if peak > PY_PEAK_LIMIT and outcome is None:
            outcome = "tracemalloc peak %d bytes" % peak
    return outcome


def _run(request: dict[str, Any], out: Any) -> dict[str, Any]:
    cid = request["codec"]
    codec = _load_codec(cid)
    gen = request["gen"]
    must_reject = gen in MUST_REJECT or gen == "reject"
    trace = cid == "py" and gen == "length"
    if trace:
        tracemalloc.start()
    count = 0
    failure = None
    try:
        for label, data in _cases(request):
            if cid == "native":
                out.write(json.dumps({"at": label}) + "\n")
                out.flush()
            count += 1
            error = _check(codec, data, must_reject, trace)
            if error is not None:
                failure = {"case": label, "error": error}
                break
    finally:
        if trace:
            tracemalloc.stop()
    return {"cases": count, "failure": failure}


def main() -> None:
    """Serve requests from stdin until it closes."""
    limit_memory(MEMORY_HEADROOM)
    out = sys.stdout
    for line in sys.stdin:
        reply = _run(json.loads(line), out)
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
