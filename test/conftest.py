"""Fixtures that run every codec test against both implementations.

The native module is optional: when it is not built (or was built for another
Python), its cases are skipped with the import error as the reason, so a run
never passes silently on the Python fallback while claiming to test native.
"""

import importlib
from types import ModuleType

import pytest

from term import py_codec_impl


# Load the optional Rust extension once; keep the reason when it is missing.
def _load_native() -> tuple[ModuleType | None, str]:
    try:
        return importlib.import_module("term.native_codec_impl"), ""
    except ImportError as e:
        return None, "native codec not built: %s" % e


_NATIVE, _NATIVE_SKIP_REASON = _load_native()

# Parameters for the `codec` fixture: the Python reference codec always, the
# native one marked skip when it cannot be imported.
_CODEC_PARAMS = [
    pytest.param(py_codec_impl, id="py"),
    pytest.param(
        _NATIVE,
        id="native",
        marks=[pytest.mark.skip(reason=_NATIVE_SKIP_REASON)] if _NATIVE is None else [],
    ),
]


@pytest.fixture(params=_CODEC_PARAMS)
def codec(request: pytest.FixtureRequest) -> ModuleType:
    """A codec implementation module: `py_codec_impl` or `native_codec_impl`."""
    impl: ModuleType = request.param
    return impl


@pytest.fixture
def native_codec() -> ModuleType:
    """The native codec module; skips the test when it is not importable."""
    if _NATIVE is None:
        pytest.skip(_NATIVE_SKIP_REASON)
    return _NATIVE
