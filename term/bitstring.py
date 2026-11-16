"""Bitstrings whose length is not a whole number of bytes."""

from term.basetypes import BaseTerm

# Mixed into the hash so that a BitString never hashes like its plain tuple.
BITSTRING_MARKER = "pyrlang.BitString"


class BitString(BaseTerm):
    """A bitstring: bytes whose last byte holds only ``last_byte_bits``
    (1..8) significant bits, the high ones. Encodes back to an Erlang
    bitstring. Decoded with the option ``"bitstring": "BitString"``.
    """

    def __init__(self, val: bytes, last_byte_bits: int) -> None:
        self.last_byte_bits_ = last_byte_bits
        self.value_ = val

    def __repr__(self) -> str:
        return "BitString(%r, %d)" % (self.value_, self.last_byte_bits_)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, BitString)
            and self.value_ == other.value_
            and self.last_byte_bits_ == other.last_byte_bits_
        )

    def __hash__(self) -> int:
        return hash((BITSTRING_MARKER, self.value_, self.last_byte_bits_))
