"""The examples in the documentation run (plan step DOCS-03).

Every ``>>>`` example of the pages in ``docs-src/source`` is executed
through ``term.codec``, as a reader would, and must print what the page
shows. The codec is the one ``term.codec`` picks: the native one where it is
built.
"""

import doctest
from pathlib import Path

import pytest

# The pages; reference pages are generated from the docstrings.
PAGES = sorted((Path(__file__).parent.parent / "docs-src" / "source").glob("*.md"))

# Exception messages differ between the codecs: the pages show the Python
# codec's, and only the exception type is compared.
FLAGS = doctest.ELLIPSIS | doctest.IGNORE_EXCEPTION_DETAIL


def _examples(page: Path) -> doctest.DocTest:
    """The ``>>>`` examples of a Markdown page. A line that closes a code
    fence ends the expected output, as a blank line does."""
    lines = page.read_text(encoding="utf-8").splitlines()
    text = "\n".join("" if line.strip() == "```" else line for line in lines)
    return doctest.DocTestParser().get_doctest(text, {}, page.name, str(page), 0)


@pytest.mark.parametrize("page", PAGES, ids=[p.name for p in PAGES])
def test_page_examples(page: Path) -> None:
    runner = doctest.DocTestRunner(optionflags=FLAGS)
    runner.run(_examples(page))
    result = runner.summarize()
    assert result.failed == 0, "%d of %d examples failed" % (
        result.failed,
        result.attempted,
    )


def test_pages_have_examples() -> None:
    """The test above is not vacuous: the two guide pages hold examples."""
    counted = {p.name: len(_examples(p).examples) for p in PAGES}
    assert counted["index.md"] > 0 and counted["data_types.md"] > 0, counted
