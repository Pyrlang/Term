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
from term.atom import Atom
from term.basetypes import BaseTerm, Term

# Mixed into the hash so that an export never hashes like a tuple of its fields.
EXPORT_MARKER = "pyrlang.Export"


class Export(BaseTerm):
    """An external fun, ``fun Module:Function/Arity`` (``EXPORT_EXT``). Not
    callable from Python, but it can be sent back to Erlang unchanged.

    :param module: the module, an atom
    :param function: the function name, an atom
    :param arity: the number of arguments, 0 or more
    """

    def __init__(self, module: str, function: str, arity: int) -> None:
        self.module_ = Atom.from_string_or_atom(module)
        self.function_ = Atom.from_string_or_atom(function)
        self.arity_ = arity

    def __repr__(self) -> str:
        return "Export(%r, %r, %d)" % (self.module_, self.function_, self.arity_)

    def __str__(self) -> str:
        return "fun %s:%s/%d" % (self.module_, self.function_, self.arity_)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Export)
            and self.module_ == other.module_
            and self.function_ == other.function_
            and self.arity_ == other.arity_
        )

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash((EXPORT_MARKER, self.module_, self.function_, self.arity_))


class Fun(BaseTerm):
    """Represents a pointer to a function in Erlang, with some variable
    values captured. Not callable from Python."""

    def __init__(
        self,
        mod: Term,
        arity: int,
        pid: Term,
        index: int,
        uniq: bytes,
        old_index: Term,
        old_uniq: Term,
        free: list[Term],
    ) -> None:
        # Pid of the Erlang process which created the function
        self.pid_ = pid

        self.arity_ = arity

        # Atom which contains the code for this function
        self.module_ = mod

        self.old_index_ = old_index

        # Internal index, an integer, in the module's internal fun table.
        # Has no meaning in Python
        self.index_ = index

        # An integer with the hash value of the function parse
        self.old_uniq_ = old_uniq

        # An md5 hash of the significant parts of the BEAM file
        self.uniq_ = uniq

        # A list of values: frozen captured variables
        self.free_ = free
