"""Sphinx configuration of the Term documentation.

Build (the same command on Windows, in WSL and in CI), with the package
installed and the ``docs`` dependency group::

    python -m sphinx -W --keep-going -b html docs-src/source docs-src/build/html
"""

import logging
import os
import sys
from datetime import date
from importlib import metadata

# Where the Pyrlang sites are published, one directory per project
# (``/pyrlang/``, ``/term/``, ``/epmd/``). ``PYRLANG_DOCS_BASE_URL`` overrides
# it for a staging host.
DOCS_BASE_URL: str = os.environ.get(
    "PYRLANG_DOCS_BASE_URL", "https://pyrlang.github.io"
).rstrip("/")

# The reference is built from the pure-Python modules: with the native codec
# blocked, term.codec falls back to term.py_codec_impl, so the pages are the
# same with and without a Rust toolchain on the build machine.
sys.modules["term.native_codec_impl"] = None  # type: ignore[assignment]  # blocks the import

# term.codec reports the fallback once at WARNING; here it is intended.
logging.getLogger("term").setLevel(logging.ERROR)

project = "Term"
author = "Dmytro Lytovchenko, Johan Sommerfeld"
copyright = "2017-%d, Erlang Solutions Ltd., S2HC Sweden AB" % date.today().year
release = metadata.version("pyrlang-term")
version = release
language = "en"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.doctest",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
]
templates_path = ["_templates"]
exclude_patterns: list[str] = []

# Every unresolved cross-reference is a warning, and the build runs with -W.
nitpicky = True
# Type variables are not objects with a page of their own.
nitpick_ignore_regex = [("py:class", r"term\.[a-z_]+\._[A-Za-z]+")]

autosummary_generate = True
# Read by _templates/autosummary/module.rst: modules left out of the
# reference. The native codec is an optional binary with the interface of
# term.codec; with it listed, the pages would depend on whether the build
# machine has a Rust toolchain.
autosummary_context = {"skip_modules": ["term.native_codec_impl"]}
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

myst_heading_anchors = 3

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

html_theme = "furo"
html_title = "Term %s" % release
html_baseurl = DOCS_BASE_URL + "/term/"
# Addresses of the sibling sites, for the links on the index page.
myst_substitutions = {
    "pyrlang_url": DOCS_BASE_URL + "/pyrlang/",
    "epmd_url": DOCS_BASE_URL + "/epmd/",
}
myst_enable_extensions = ["substitution"]
