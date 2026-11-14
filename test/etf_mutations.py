"""Ways to break valid ETF bytes, for the malformed-input tests (TERM-05).

Three generators turn one valid term (``131`` + term) into many broken ones.
Each yields ``(label, bytes)``; the label says where the input was changed.

- ``truncations``: the input cut short at an offset. ETF terms are
  self-delimiting, so a strict prefix of a term never is a complete term:
  every truncation must be rejected.
- ``length_maxed``: one length or count field set to the largest value its
  width holds, where that value asks for more bytes than are left. Every such
  mutation must be rejected.
- ``bit_flips``: one byte xor-ed with each mask of OTP's ``corrupter``
  (``binary_SUITE:bad_terms``). The result may still be a valid term, so a
  decoder may return a value; it must not raise anything but
  ``PyCodecError``.

``walk`` reads the structure of a valid term well enough to find its length
fields. It trusts its input: it is only given OTP-written fixtures.
"""

import struct
from collections.abc import Iterator
from dataclasses import dataclass, field

# OTP's corrupter flips these masks into each byte (binary_SUITE:corrupter).
FLIP_MASKS = (1, 2, 4, 8, 16, 32, 64, 128, 255)

# Inputs longer than this are cut or flipped at a sample of offsets only:
# decoding is linear (or worse) in the input, so every offset of a 128 KiB
# fixture would take hours in the Python codec.
TRUNCATE_BUDGET = 256
FLIP_BUDGET = 64

# Tag bytes as named in OTP's erl_ext_dist.
_COMPRESSED = 80
_VERSION = 131


# A length or count field in an encoded term.
@dataclass(frozen=True)
class LengthField:
    offset: int  # position in the whole input (the 131 byte is offset 0)
    width: int  # 1, 2 or 4 bytes, big-endian
    tag: int  # tag byte of the term the field belongs to
    # Fewest input bytes one counted unit takes (1 for bytes and for terms,
    # 4 for reference words); 0 for the declared size of compressed data,
    # which no remaining-input check applies to.
    unit: int


# What ``walk`` found in one encoded term.
@dataclass
class Shape:
    fields: list[LengthField] = field(default_factory=list)
    tags: set[int] = field(default_factory=set)


def walk(data: bytes) -> Shape:
    """The length fields and tags of a valid ``131``-prefixed term.

    A compressed term is not inflated: only its declared size is a field.
    """
    if data[0] != _VERSION:
        raise ValueError("not an ETF term: first byte %d" % data[0])
    shape = Shape()
    if data[1] == _COMPRESSED:
        shape.tags.add(_COMPRESSED)
        shape.fields.append(LengthField(2, 4, _COMPRESSED, 0))
        return shape
    end = _Walker(data, shape).term(1)
    if end != len(data):
        raise ValueError("term ends at %d of %d bytes" % (end, len(data)))
    return shape


# Recursive reader over a valid term; records fields and tags into a Shape.
class _Walker:
    def __init__(self, data: bytes, shape: Shape) -> None:
        self.data_ = data
        self.shape_ = shape

    def _len(self, pos: int, width: int, tag: int, unit: int = 1) -> int:
        self.shape_.fields.append(LengthField(pos, width, tag, unit))
        fmt = {1: ">B", 2: ">H", 4: ">I"}[width]
        value: int = struct.unpack_from(fmt, self.data_, pos)[0]
        return value

    def _terms(self, pos: int, count: int) -> int:
        for _ in range(count):
            pos = self.term(pos)
        return pos

    def term(self, pos: int) -> int:
        """Walk the term at ``pos``; return the offset just after it."""
        tag = self.data_[pos]
        self.shape_.tags.add(tag)
        fixed = _FIXED_SIZE.get(tag)
        if fixed is not None:
            return pos + fixed
        if tag in (100, 118):  # ATOM_EXT, ATOM_UTF8_EXT
            return pos + 3 + self._len(pos + 1, 2, tag)
        if tag in (115, 119):  # SMALL_ATOM_EXT, SMALL_ATOM_UTF8_EXT
            return pos + 2 + self._len(pos + 1, 1, tag)
        if tag == 107:  # STRING_EXT
            return pos + 3 + self._len(pos + 1, 2, tag)
        if tag == 109:  # BINARY_EXT
            return pos + 5 + self._len(pos + 1, 4, tag)
        if tag == 77:  # BIT_BINARY_EXT: Len, Bits, Data
            return pos + 6 + self._len(pos + 1, 4, tag)
        if tag == 110:  # SMALL_BIG_EXT: n, Sign, digits
            return pos + 3 + self._len(pos + 1, 1, tag)
        if tag == 111:  # LARGE_BIG_EXT
            return pos + 6 + self._len(pos + 1, 4, tag)
        if tag == 104:  # SMALL_TUPLE_EXT
            return self._terms(pos + 2, self._len(pos + 1, 1, tag))
        if tag == 105:  # LARGE_TUPLE_EXT
            return self._terms(pos + 5, self._len(pos + 1, 4, tag))
        if tag == 108:  # LIST_EXT: elements, then the tail
            return self.term(self._terms(pos + 5, self._len(pos + 1, 4, tag)))
        if tag == 116:  # MAP_EXT: Arity pairs
            return self._terms(pos + 5, 2 * self._len(pos + 1, 4, tag))
        if tag in _NODE_THEN:  # pids, ports, REFERENCE_EXT: Node, fixed tail
            return self.term(pos + 1) + _NODE_THEN[tag]
        if tag == 114:  # NEW_REFERENCE_EXT: Len, Node, Creation:8, ID words
            words = self._len(pos + 1, 2, tag, unit=4)
            return self.term(pos + 3) + 1 + 4 * words
        if tag == 90:  # NEWER_REFERENCE_EXT: Len, Node, Creation:32, ID words
            words = self._len(pos + 1, 2, tag, unit=4)
            return self.term(pos + 3) + 4 + 4 * words
        if tag == 112:  # NEW_FUN_EXT
            # Size (pos + 1) is not a field here: OTP 29 decodes a fun whose
            # Size is 0xFFFFFFFF (ERTS ignores it since 13.1, OTP-18104).
            num_free = self._len(pos + 26, 4, tag)
            # Module, OldIndex, OldUniq, Pid, then NumFree free variables.
            return self._terms(pos + 30, 4 + num_free)
        if tag == 113:  # EXPORT_EXT: Module, Function, Arity
            return self._terms(pos + 1, 3)
        if tag == 67:  # RECORD_EXT: #Fields, Flags, Module, Name, names, values
            count = self._len(pos + 1, 4, tag)
            return self._terms(pos + 6, 2 + 2 * count)
        raise ValueError("tag %d at offset %d is not walked" % (tag, pos))


# Terms of fixed size, tag byte included.
_FIXED_SIZE: dict[int, int] = {
    97: 2,  # SMALL_INTEGER_EXT
    98: 5,  # INTEGER_EXT
    70: 9,  # NEW_FLOAT_EXT
    99: 32,  # FLOAT_EXT
    106: 1,  # NIL_EXT
}

# Node containers: bytes that follow the Node atom.
_NODE_THEN: dict[int, int] = {
    103: 9,  # PID_EXT: ID:32, Serial:32, Creation:8
    88: 12,  # NEW_PID_EXT: ID:32, Serial:32, Creation:32
    102: 5,  # PORT_EXT: ID:32, Creation:8
    89: 8,  # NEW_PORT_EXT: ID:32, Creation:32
    120: 12,  # V4_PORT_EXT: ID:64, Creation:32
    101: 5,  # REFERENCE_EXT: ID:32, Creation:8
}


def sample_offsets(size: int, budget: int) -> list[int]:
    """Offsets ``0 .. size-1``, or ``budget`` of them when there are more.

    The sample keeps the first half of the budget and the last quarter of the
    offsets (where headers and the outermost tails are) and spreads the rest
    evenly over the middle.
    """
    if size <= budget:
        return list(range(size))
    head = budget // 2
    tail = budget // 4
    middle = budget - head - tail
    picked = set(range(head)) | set(range(size - tail, size))
    step = (size - tail - head) / (middle + 1)
    picked |= {head + int(step * (i + 1)) for i in range(middle)}
    return sorted(picked)


def truncations(
    data: bytes, budget: int = TRUNCATE_BUDGET
) -> Iterator[tuple[str, bytes]]:
    """``data`` cut short at each (sampled) offset."""
    for n in sample_offsets(len(data), budget):
        yield "truncated to %d of %d bytes" % (n, len(data)), data[:n]


def length_maxed(data: bytes) -> Iterator[tuple[str, bytes]]:
    """``data`` with one length field at a maximum the input cannot hold."""
    for f in walk(data).fields:
        biggest = (1 << (8 * f.width)) - 1
        left = len(data) - f.offset - f.width
        if f.unit and biggest * f.unit <= left:
            continue  # the input could hold that many: no longer surely bad
        mutated = data[: f.offset] + b"\xff" * f.width + data[f.offset + f.width :]
        yield "tag %d length at offset %d set to 0x%X" % (
            f.tag,
            f.offset,
            biggest,
        ), mutated


def bit_flips(data: bytes) -> Iterator[tuple[str, bytes]]:
    """``data`` with one byte xor-ed with each corrupter mask."""
    for pos in sample_offsets(len(data), FLIP_BUDGET):
        for mask in FLIP_MASKS:
            flipped = data[:pos] + bytes([data[pos] ^ mask]) + data[pos + 1 :]
            yield "byte %d xor 0x%02X" % (pos, mask), flipped


# The generators by name, as test ids and worker requests use them.
GENERATORS = {
    "truncate": truncations,
    "length": length_maxed,
    "flip": bit_flips,
}

# Generators whose every output must be rejected; ``flip`` output may decode.
MUST_REJECT = {"truncate", "length"}
