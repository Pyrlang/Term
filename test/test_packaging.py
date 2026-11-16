"""Packaging facts no build checks by itself (plan step TERM-19)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_one_version() -> None:
    """The version is pyproject.toml's; Cargo.toml carries it in semver form
    (YYYY.BUILD-TAG becomes YYYY.BUILD.0-TAG) and bumpver knows it."""
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    version = py["project"]["version"]
    m = re.fullmatch(r"(\d+)\.(\d+)(?:-(\w+))?", version)
    assert m is not None, version
    semver = "%s.%s.0" % (m[1], m[2]) + ("-" + m[3] if m[3] else "")
    assert cargo["package"]["version"] == semver
    assert py["tool"]["bumpver"]["current_version"] == version
    assert not (ROOT / "setup.py").exists()
