"""Generic ddmin: textbook delta debugging over lists (Zeller & Hildebrandt).

`ddmin(items, test)` returns a minimal sublist of `items` for which
`test(candidate) -> bool` still holds ("interesting"), using complement
partitioning with granularity doubling. `test` is invoked on candidate
sublists only; callers charge their own budget by wrapping `test`.

Properties relied upon by the reducer:
  - the result is never a superset of any accepted intermediate candidate
    (the search only ever moves to accepted, smaller candidates);
  - 1-minimality is NOT guaranteed (that is T1.6's verified pass).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def ddmin(items: list[T], test: Callable[[list[T]], bool]) -> list[T]:
    current = list(items)
    n = 2
    while len(current) >= 2:
        k = (len(current) + n - 1) // n  # subset length (ceil)
        spans = [(i, min(i + k, len(current))) for i in range(0, len(current), k)]
        reduced = False
        # try removing each subset (test its positional complement)
        for i, j in spans:
            complement = current[:i] + current[j:]
            if test(complement):
                current = complement
                n = max(n - 1, 2)
                reduced = True
                break
        if reduced:
            continue
        # try each subset itself (the interesting part may be small)
        for i, j in spans:
            if test(current[i:j]):
                current = current[i:j]
                n = 2
                reduced = True
                break
        if reduced:
            continue
        if n >= len(current):
            break
        n = min(n * 2, len(current))
    return current
