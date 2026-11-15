# Copyright 2026, the Pyrlang authors
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
from term.atom import Atom
from term.basetypes import BaseTerm

# Mixed into the hash so that a port never hashes like a tuple of its fields.
PORT_MARKER = "pyrlang.Port"


class Port(BaseTerm):
    """An Erlang port identifier from another node. Python cannot use it,
    but it can store it and send it back unchanged: since OTP 26 every node
    must accept ports with 64-bit ids (``DFLAG_V4_NC``).

    :param node_name: the node that owns the port
    :param id: the port number, 0 .. 2^64-1
    :param creation: the incarnation of that node, 0 .. 2^32-1
    """

    def __init__(self, node_name: str, id: int, creation: int) -> None:
        self.node_name_ = Atom.from_string_or_atom(node_name)
        self.id_ = id
        self.creation_ = creation

    def __repr__(self) -> str:
        return "#Port<%d.%d @ %s>" % (self.creation_, self.id_, self.node_name_)

    def __str__(self) -> str:
        return self.__repr__()

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Port)
            and self.node_name_ == other.node_name_
            and self.id_ == other.id_
            and self.creation_ == other.creation_
        )

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash((PORT_MARKER, self.node_name_, self.id_, self.creation_))
