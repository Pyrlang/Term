"""The Erlang/OTP that judges the codecs in the ``erlang``-marked tests.

``$PYRLANG_ERL`` picks the ``erl`` to use, for example one release of the WSL
matrix (``tools/otp-matrix.sh`` in the workspace); otherwise ``erl`` on
``PATH``. Without either, those tests skip. A ``$PYRLANG_ERL`` that does not
run makes them fail, so a matrix run cannot pass without its release.
"""

import functools
import os
import shutil
import subprocess

# The erl executable, or None when there is none to run.
ERL: str | None = os.environ.get("PYRLANG_ERL") or shutil.which("erl")


@functools.cache
def otp_release() -> int:
    """The major OTP release of ``ERL``."""
    assert ERL is not None
    proc = subprocess.run(
        [
            ERL,
            "-noshell",
            "-eval",
            "io:put_chars(erlang:system_info(otp_release)), halt().",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    return int(proc.stdout.strip())
