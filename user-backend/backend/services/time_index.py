"""Integer match-clock segment tree over 0..12000 s: a point probes fifteen nodes and returns each matching
rule once. Fractional rule bounds keep strict/inclusive semantics.
"""
from collections import defaultdict
from math import ceil, floor

from backend.models.rules import Predicate


class TimeIndex:
    SIZE = 16384

    def __init__(self):
        self._nodes: dict[int, list[str]] = defaultdict(list)
        self._all: list[str] = []
        self.last_probe_count = 0

    def add(self, identifier: str, predicates: tuple[Predicate, ...]):
        lower, upper, points = 0, 12000, None
        for predicate in predicates:
            value, op = predicate.value, predicate.op
            if op in {"eq", "in"}:
                values = (value,) if op == "eq" else value
                integers = {int(v) for v in values if v == int(v)}
                points = integers if points is None else points & integers
            elif op == "gt":
                lower = max(lower, floor(value) + 1)
            elif op == "gte":
                lower = max(lower, ceil(value))
            elif op == "lt":
                upper = min(upper, ceil(value) - 1)
            else:
                upper = min(upper, floor(value))
        intervals = [(lower, upper)] if points is None else [(v, v) for v in points if lower <= v <= upper]
        for start, end in intervals:
            if start > end:
                continue
            if start == 0 and end == 12000:
                self._all.append(identifier)
                continue
            left, right = start + self.SIZE, end + self.SIZE
            while left <= right:
                if left & 1:
                    self._nodes[left].append(identifier)
                    left += 1
                if not right & 1:
                    self._nodes[right].append(identifier)
                    right -= 1
                left //= 2
                right //= 2

    def matching(self, second: int) -> list[str]:
        self.last_probe_count = 0
        matches = list(self._all)
        if not self._nodes:
            return matches
        node = second + self.SIZE
        while node:
            matches.extend(self._nodes.get(node, ()))
            self.last_probe_count += 1
            node //= 2
        return matches
