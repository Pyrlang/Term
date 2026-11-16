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
"""Improper lists, and helpers for lists of code points."""

import array
from typing import Any, List

from term.basetypes import BaseTerm

NIL: List[Any] = []

# Default of ImproperList's tail argument: tells "omitted" apart from a tail
# that is falsy (0, None, "") but still a tail.
_NO_TAIL: Any = object()


class ImproperList(List, BaseTerm):
    """A simple data holder used to pass improper lists back to Erlang.
    An Erlang improper list looks like `[1, 2, 3 | 4]` where 4 takes
    tail slot of last list cell instead of `NIL`. This is a rare data type
    and very likely you will not ever need it.
    """

    def __init__(self, elements: list[Any], tail: Any = _NO_TAIL) -> None:
        """tail is optional, if omitted, the last element in elements
        `elements[-1]` will be considered to be the tail. if it's
        present (whatever its value, 0 and None included) it will be
        appended to the list so it becomes `self[-1]`
        """
        super().__init__(elements)
        if tail is not _NO_TAIL:
            self.append(tail)

    @property
    def _elements(self) -> list[Any]:
        return self[:-1]

    @property
    def _tail(self) -> Any:
        return self[-1]


def list_to_unicode_str(lst: list[int]) -> str:
    """A helper function to convert a list of large integers incoming from
    Erlang into a unicode string."""
    return "".join(map(chr, lst))


def list_to_str(lst: list[int]) -> str:
    """A helper function to convert a list of bytes (0..255) into an
    ASCII string."""
    return bytearray(lst).decode("utf-8")
