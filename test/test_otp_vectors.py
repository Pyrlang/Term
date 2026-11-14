"""Decode the vectors copied from OTP's own test suites (plan step TERM-04).

The vectors in ``test/fixtures/otp`` come from ``test/erl/otp_vectors.erl``.
Each vector's ``origin`` (also the start of its name) is the OTP test case it
was taken from, e.g. ``binary_SUITE.terms.012`` is from
``binary_SUITE:terms``. Most are ``term_to_binary`` output of OTP 29; the rest
are bytes written as they are: what the C ``ei`` encoder writes
(``ei_encode_SUITE``), hand-built non-optimal integers and Latin-1 atoms
(``ei_decode_SUITE``), and pids, ports and refs with the old tags
(``node_container_SUITE``, ``ei_decode_encode_SUITE``).

Here both codecs decode every vector; ``test_roundtrip.py`` lets OTP judge
the values.
"""

from types import ModuleType

import pytest
from fixture_manifest import (
    OTP_VECTOR_DIR,
    REJECTED_FEATURE,
    REJECTED_WRONGLY_BY,
    Vector,
    codec_id,
    decode_blocker,
    load_vectors,
)

VECTORS = load_vectors(OTP_VECTOR_DIR)


def test_manifest_matches_files() -> None:
    """Every vector file is in the manifest and every manifest entry exists."""
    on_disk = {p.stem for p in OTP_VECTOR_DIR.glob("*.etf")}
    listed = [v.name for v in VECTORS]
    assert len(listed) == len(set(listed))
    assert on_disk == set(listed)


def test_every_origin_is_named() -> None:
    """Each vector names the OTP suite (and case) it comes from."""
    for v in VECTORS:
        assert v.origin.split(":")[0].endswith("_SUITE"), v.name
        assert v.name.startswith(v.origin.replace(":", ".") + "."), v.name


@pytest.mark.parametrize("vector", VECTORS, ids=[v.name for v in VECTORS])
def test_decode_otp_vector(
    vector: Vector, codec: ModuleType, request: pytest.FixtureRequest
) -> None:
    cid = codec_id(codec)
    data = vector.path.read_bytes()
    step = decode_blocker(vector, cid)

    if step is None and REJECTED_FEATURE in vector.features:
        step = REJECTED_WRONGLY_BY.get(cid)
        if step is not None:
            request.applymarker(pytest.mark.xfail(strict=True, reason=step))
        with pytest.raises(codec.PyCodecError):
            codec.binary_to_term(data, None)
        return

    if step is not None:
        request.applymarker(pytest.mark.xfail(strict=True, reason=step))
    _value, tail = codec.binary_to_term(data, None)
    assert tail == b""
