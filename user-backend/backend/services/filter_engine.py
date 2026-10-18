"""Shared in-memory indexed calculations. No database, network or generated exec.

Each rule chooses one compound equality/membership index. An event probes at
most 64 field masks, independent of rule count. Range-only rules use a match
wildcard; genuinely relevant rules still cost work. Caller serializes mutations.
"""
from collections import defaultdict
from decimal import Decimal
from itertools import product

from pydantic import BaseModel, ConfigDict

from backend.models.events import Event
from backend.models.rules import INDEX_FIELDS, Rule


class CalculationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    calculation_id: str
    value: float
    version: int


class FilterEngine:
    def __init__(self):
        self._rules: dict[str, Rule] = {}
        self._results: dict[str, CalculationResult] = {}
        self._totals: dict[str, Decimal] = {}
        self._events: dict[tuple[str, str], Event] = {}
        self._index = defaultdict(lambda: defaultdict(set))
        self.last_candidate_count = 0
        self.last_index_probe_count = 0

    @property
    def rules(self) -> dict[str, Rule]:
        return dict(self._rules)

    @property
    def calculations(self) -> list[CalculationResult]:
        return list(self._results.values())

    @property
    def count(self) -> int:
        return len(self._rules)

    def rule(self, calculation_id: str) -> Rule:
        return self._rules[calculation_id]

    def get(self, calculation_id: str) -> CalculationResult:
        return self._results[calculation_id]

    def restore_version(self, calculation_id: str, version: int) -> CalculationResult:
        """Restore a persisted delivery version after rebuilding from history."""
        current = self.get(calculation_id)
        if isinstance(version, bool) or not isinstance(version, int) or version < current.version:
            raise ValueError("Restored version cannot move backwards")
        self._results[calculation_id] = current.model_copy(update={"version": version})
        return self.get(calculation_id)

    def _keys(self, rule):
        constraints = {}
        for predicate in rule.predicates:
            if predicate.field in INDEX_FIELDS and predicate.op in {"eq", "in"}:
                values = {predicate.value} if predicate.op == "eq" else set(predicate.value)
                constraints[predicate.field] = constraints.get(predicate.field, values) & values
        if any(not values for values in constraints.values()):
            return ()  # Unsatisfiable equality conjunction never matches.
        fields, options, combinations = [], [], 1
        # Keep membership expansion bounded; remaining conditions are evaluated later.
        for field in INDEX_FIELDS:
            values = constraints.get(field)
            if values and combinations * len(values) <= 64:
                fields.append(field)
                options.append(sorted(values))
                combinations *= len(values)
        return [(tuple(fields), values) for values in product(*options)]

    def register(self, rule: Rule, history=()) -> CalculationResult:
        # History revisions also update other registered calculations. Callers must
        # publish changed results if importing unseen revisions into an active engine.
        for event in history:
            self.ingest(event)
        identifier = rule.calculation_id
        if identifier in self._rules:
            return self.get(identifier)
        # Decimal accumulation keeps streaming and backfill independent of float
        # addition order (including subtracting a corrected measurement).
        value = sum((Decimal(str(rule.contribution(e))) for e in self._events.values()), Decimal(0))
        self._rules[identifier] = rule
        self._totals[identifier] = value
        self._results[identifier] = CalculationResult(calculation_id=identifier, value=float(value), version=1)
        for fields, values in self._keys(rule):
            self._index[rule.match_id][fields, values].add(identifier)
        return self.get(identifier)

    def _candidates(self, event):
        # Masks are bounded by 2**len(INDEX_FIELDS), not derived by scanning rules.
        candidates = set()
        match_index = self._index.get(event.match_id, {})
        for mask in range(1 << len(INDEX_FIELDS)):
            fields = tuple(field for bit, field in enumerate(INDEX_FIELDS) if mask & (1 << bit))
            values = tuple(getattr(event, field) for field in fields)
            candidates.update(match_index.get((fields, values), ()))
            self.last_index_probe_count += 1
        return candidates

    def ingest(self, event: Event) -> list[CalculationResult]:
        self.last_candidate_count = self.last_index_probe_count = 0
        key = (event.match_id, event.event_id)
        previous = self._events.get(key)
        if previous and event.revision <= previous.revision:
            if event.revision == previous.revision and event != previous:
                raise ValueError("Conflicting contents for the same event revision")
            return []
        candidates = self._candidates(event)
        if previous:
            candidates.update(self._candidates(previous))
        self.last_candidate_count = len(candidates)
        self._events[key] = event
        changed = []
        for identifier in sorted(candidates):
            rule, result = self._rules[identifier], self._results[identifier]
            delta = Decimal(str(rule.contribution(event))) - Decimal(str(rule.contribution(previous)))
            if delta:
                self._totals[identifier] += delta
                result = CalculationResult(calculation_id=identifier, value=float(self._totals[identifier]), version=result.version + 1)
                self._results[identifier] = result
                changed.append(result)
        return changed
