"""Packaging facts no build checks by itself (plan step TERM-19)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_one_version() -> None:
    """The version is pyproject.toml's, MAJOR.MINOR.PATCH; Cargo.toml carries
    the same string and bumpver knows it."""
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    version = py["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    assert cargo["package"]["version"] == version
    assert py["tool"]["bumpver"]["current_version"] == version
    assert not (ROOT / "setup.py").exists()
