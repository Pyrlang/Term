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
"""Native records (Erlang/OTP 29)."""

from typing import Any

from term.atom import Atom
from term.basetypes import BaseTerm

# Mixed into the hash so that a record never hashes like a tuple of its fields.
RECORD_MARKER = "pyrlang.Record"


class Record(BaseTerm):
    """A native record (EEP-79, OTP 29, ``RECORD_EXT``): ``#Module:Name{...}``.
    Native records are experimental in OTP 29 and 30.

    :param module: the module that defines the record, an atom
    :param name: the record name, an atom
    :param exported: whether the module exports the record definition
    :param fields: field name (atom) -> value, in the order of the
        definition; encoded in this order
    """

    def __init__(
        self, module: str, name: str, exported: bool, fields: dict[str, Any]
    ) -> None:
        self.module_ = Atom.from_string_or_atom(module)
        self.name_ = Atom.from_string_or_atom(name)
        self.exported_ = exported
        # Values are any decoded term, hence Any.
        self.fields_ = fields

    def __repr__(self) -> str:
        return "Record(%r, %r, exported=%r, %r)" % (
            self.module_,
            self.name_,
            self.exported_,
            self.fields_,
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Record)
            and self.module_ == other.module_
            and self.name_ == other.name_
            and self.exported_ == other.exported_
            and self.fields_ == other.fields_
        )

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        # Field values may be unhashable (lists); equal records still hash
        # equally, as they have the same field names.
        return hash(
            (
                RECORD_MARKER,
                self.module_,
                self.name_,
                self.exported_,
                frozenset(self.fields_),
            )
        )
