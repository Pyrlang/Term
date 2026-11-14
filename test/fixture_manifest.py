"""The OTP-written fixture sets and the plan steps that still block them.

``test/erl/gen_fixtures.erl`` writes two sets, each with a ``MANIFEST.tsv``:

- ``test/fixtures``: the golden fixtures of plan step TERM-03;
- ``test/fixtures/otp``: terms and byte vectors copied from OTP's own test
  suites (TERM-04); the ``origin`` column names the suite and case.

Both manifests have a ``features`` column: what the term contains that our
codecs cannot handle yet (see ``features/2`` in ``gen_fixtures.erl``). The
tables below map each feature to the plan step that fixes it. When a step is
done, delete its lines here; strict xfails show any table that is wrong.
"""

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from term import py_codec_impl

# Where gen_fixtures.erl writes the two sets.
FIXTURE_DIR = Path(__file__).parent / "fixtures"
OTP_VECTOR_DIR = FIXTURE_DIR / "otp"

# Features that neither codec decodes yet -> plan step.
DECODE_BLOCKED: dict[str, str] = {
    "port": "TERM-10",
    "reference_ext": "TERM-11",
    "export_fun": "TERM-12",
    "float_ext": "TERM-14",
    "record": "TERM-17",
}

# Features that one codec does not decode yet: (feature, codec id) -> step.
DECODE_BLOCKED_BY: dict[tuple[str, str], str] = {
    # Native decodes STRING_EXT as UTF-8 and fails on bytes >= 128.
    ("str_latin1", "native"): "TERM-07",
}

# Features that decode but do not come back as the same term after
# decode -> encode (in addition to everything that does not decode).
ROUNDTRIP_BLOCKED: dict[str, str] = {
    # Both encoders write the decoded str as UTF-8 into STRING_EXT.
    "str_latin1": "TERM-07",
    "local_fun": "TERM-13",
    # Bitstrings decode to a (bytes, bits) tuple, which encodes as a tuple.
    "bitstring": "TERM-20",
}

ROUNDTRIP_BLOCKED_BY: dict[tuple[str, str], str] = {
    # Python packs these with struct ">i" and raises struct.error.
    ("int_bits_32", "py"): "TERM-07",
}

# Terms with no Python value (a map key that would be a list or a dict):
# decoding must raise PyCodecError.
REJECTED_FEATURE = "unhashable_key"

# Codecs that get the rejection wrong yet: codec id -> plan step.
REJECTED_WRONGLY_BY: dict[str, str] = {
    # The Python codec lets the dict's TypeError escape.
    "py": "TERM-08",
}


# One line of a MANIFEST.tsv.
@dataclass(frozen=True)
class Vector:
    name: str
    path: Path
    origin: str
    features: frozenset[str]


def load_vectors(directory: Path) -> list[Vector]:
    """All vectors listed in ``directory/MANIFEST.tsv``."""
    lines = (directory / "MANIFEST.tsv").read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    vectors = []
    for line in lines[1:]:
        row = dict(zip(header, line.split("\t"), strict=True))
        features = frozenset(f for f in row["features"].split(",") if f)
        vectors.append(
            Vector(
                name=row["name"],
                path=directory / (row["name"] + ".etf"),
                # The golden set has no origin column: gen_fixtures.erl built it.
                origin=row.get("origin", "gen_fixtures"),
                features=features,
            )
        )
    return vectors


def codec_id(codec: ModuleType) -> str:
    """``py`` or ``native``, as in the ids of the ``codec`` fixture."""
    return "py" if codec is py_codec_impl else "native"


def _steps(
    features: frozenset[str],
    cid: str,
    tables: list[dict[str, str]],
    tables_by: list[dict[tuple[str, str], str]],
) -> str | None:
    steps = {t[f] for t in tables for f in features if f in t}
    steps |= {t[(f, cid)] for t in tables_by for f in features if (f, cid) in t}
    return ", ".join(sorted(steps)) or None


def decode_blocker(vector: Vector, cid: str) -> str | None:
    """The plan steps that must land before ``cid`` decodes this vector."""
    return _steps(vector.features, cid, [DECODE_BLOCKED], [DECODE_BLOCKED_BY])


def roundtrip_blocker(vector: Vector, cid: str) -> str | None:
    """The plan steps that must land before this vector survives
    decode -> encode with ``cid`` unchanged."""
    return _steps(
        vector.features,
        cid,
        [DECODE_BLOCKED, ROUNDTRIP_BLOCKED],
        [DECODE_BLOCKED_BY, ROUNDTRIP_BLOCKED_BY],
    )
