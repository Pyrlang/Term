from term import atom as a
from term import pid as p
from term import reference as r
from term import fun as f

from typing import Union, List, Any

AnyTerm = Union[str, List[Any], tuple, dict, int, float, bytes,
                a.Atom, p.Pid, r.Reference, f.Fun]
