# Copyright 2018, Erlang Solutions Ltd, and S2HC Sweden AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Erlang references."""

import itertools
import random
import struct

from term import Atom, util
from term.basetypes import BaseRef, Term

REF_MARKER = "pyrlang.Ref"

# Numbers the references that Reference.create makes in this process, so
# that no two of them are equal.
_CREATED = itertools.count(1)

# The 3 ID words of a created reference.
_REF_WORDS = struct.Struct(">III")


class Reference(BaseRef):
    """Represents a reference value from Erlang, typically it has 12 bytes of
    unique data, but it might change.
    """

    @staticmethod
    def create(node_name: str, creation: int) -> "Reference":
        """A new reference of node ``node_name``, unequal to every other
        reference this process creates.

        Its 3 ID words hold a per-process counter (the low 18 bits in the
        first word, the next 32 in the second) and 32 random bits (third),
        so a restarted node is unlikely to repeat references it made before.

        :param node_name: string, not a Node object
        :param creation: the creation of the node's distribution
        :rtype: term.reference.Reference
        """
        n = next(_CREATED)
        refid = _REF_WORDS.pack(
            n & 0x3FFFF, (n >> 18) & 0xFFFFFFFF, random.getrandbits(32)
        )
        return Reference(node_name=node_name, creation=creation, refid=refid)

    def __init__(self, node_name: Term, creation: int, refid: bytes) -> None:
        self.node_name_ = Atom.from_string_or_atom(node_name)
        """ Node the ref comes from. NOTE: native codec assumes this is a string. """

        self.id_ = refid
        """ Identification bytes, guaranteed to be unique on the creating node """

        self.creation_ = creation

    def __repr__(self) -> str:
        # Assume that ref has only 3 32-bit words (actually id size is not
        # specified in docs and can be a different multiple of 4)
        if len(self.id_) == 12:
            v = struct.unpack(">III", self.id_)
            return "Ref<%d,%d,%d,%d>@%s" % (
                self.creation_,
                v[0],
                v[1],
                v[2],
                self.node_name_,
            )
        else:
            return "Ref<%d,%s>" % (self.creation_, util.hex_bytes(self.id_, ","))

    def __str__(self) -> str:
        return self.__repr__()

    # Eq, Ne and Hash are used for having this class as a dict key

    def equals(self, other: object) -> bool:
        """True if ``other`` is the same reference: node, creation and id."""
        return (
            isinstance(other, Reference)
            and self.node_name_ == other.node_name_
            and self.id_ == other.id_
            and self.creation_ == other.creation_
        )

    __eq__ = equals

    def __ne__(self, other: object) -> bool:
        return not self.equals(other)

    def __hash__(self) -> int:
        return hash((REF_MARKER, self.node_name_, self.id_, self.creation_))
