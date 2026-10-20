"""Shared in-memory indexed calculations. No database, network or generated exec.

Rules with the same non-clock predicates share one predicate evaluation. A
compound index selects those families, then a clock index selects their windows.
Changed result materialization still costs O(changed rules). Caller serializes
mutations; this engine does not route results to individual viewers.
"""
from collections import defaultdict
from decimal import Decimal
from itertools import product

from pydantic import BaseModel, ConfigDict

from backend.models.events import Event
from backend.models.rules import INDEX_FIELDS, Rule
from backend.services.time_index import TimeIndex


class CalculationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    calculation_id: str
    value: float | None
    version: int


class FilterEngine:
    def __init__(self):
        self._rules: dict[str, Rule] = {}
        self._visible: set[str] = set()
        self._dependents: dict[str, set[str]] = defaultdict(set)
        self._formula_inputs: dict[str, tuple[str, str]] = {}
        self.last_formula_evaluation_count = 0
        self._results: dict[str, CalculationResult] = {}
        self._totals: dict[str, Decimal] = {}
        self._events: dict[tuple[str, str], Event] = {}
        self._index = defaultdict(lambda: defaultdict(set))
        self._families: dict[str, tuple[Rule, TimeIndex]] = {}
        self.last_candidate_count = 0
        self.last_index_probe_count = 0
        self.last_family_evaluation_count = 0
        self.last_time_probe_count = 0

    @property
    def rules(self) -> dict[str, Rule]:
        return {key: value for key, value in self._rules.items() if key in self._visible}

    @property
    def calculations(self) -> list[CalculationResult]:
        return [value for key, value in self._results.items() if key in self._visible]

    @property
    def count(self) -> int:
        return len(self._visible)

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

    def register(self, rule: Rule, history=(), *, _visible=True) -> CalculationResult:
        # History revisions also update other registered calculations. Callers must
        # publish changed results if importing unseen revisions into an active engine.
        for event in history:
            self.ingest(event)
        identifier = rule.calculation_id
        promoted = _visible and identifier not in self._visible
        if _visible:
            self._visible.add(identifier)
        if identifier in self._rules:
            if promoted:
                self._results[identifier] = self._results[identifier].model_copy(update={"version": 1})
            return self.get(identifier)
        if rule.composite:
            for source in rule.inputs:
                self.register(Rule.model_validate(source.model_dump()), _visible=False)
                self._dependents[source.calculation_id].add(identifier)
            self._rules[identifier] = rule
            self._formula_inputs[identifier] = tuple(item.calculation_id for item in rule.inputs)
            self._results[identifier] = CalculationResult(calculation_id=identifier,
                value=self._formula_value(identifier), version=1)
            return self.get(identifier)
        # Decimal avoids ordinary binary-float accumulation drift, but its
        # precision is bounded; see docs/filter-engine-design.md for the contract.
        value = sum((Decimal(str(rule.contribution(e))) for e in self._events.values()), Decimal(0))
        self._rules[identifier] = rule
        self._totals[identifier] = value
        self._results[identifier] = CalculationResult(calculation_id=identifier, value=float(value), version=1)
        # Keep operation in the family identity: count and sum share matching
        # behaviour but have different event contributions.
        base = rule.model_copy(update={"predicates": tuple(p for p in rule.predicates if p.field != "match_time_seconds")})
        family_id = base.calculation_id
        if family_id not in self._families:
            self._families[family_id] = base, TimeIndex()
            for fields, values in self._keys(base):
                self._index[rule.match_id][fields, values].add(family_id)
        self._families[family_id][1].add(identifier, tuple(p for p in rule.predicates if p.field == "match_time_seconds"))
        return self.get(identifier)

    @property
    def leaf_count(self):
        return len(self._totals)

    def _formula_value(self, identifier):
        rule = self._rules[identifier]
        left, right = (self._totals[source] for source in self._formula_inputs[identifier])
        if rule.operation == 'difference':
            return float(left - right)
        if not right:
            return None
        return float(left / right * (100 if rule.operation == 'percentage' else 1))

    def _refresh_formulas(self, changed):
        affected = set()
        for result in changed:
            affected.update(self._dependents.get(result.calculation_id, ()))
        self.last_formula_evaluation_count = len(affected)
        for identifier in affected:
            value = self._formula_value(identifier)
            current = self._results[identifier]
            if current.value != value:
                result = CalculationResult(calculation_id=identifier, value=value, version=current.version + 1)
                self._results[identifier] = result
                changed.append(result)

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

    def _groups(self, event):
        groups = []
        if event is None:
            return groups
        for family_id in self._candidates(event):
            base, clock = self._families[family_id]
            identifiers = clock.matching(event.match_time_seconds)
            self.last_time_probe_count += clock.last_probe_count
            self.last_candidate_count += len(identifiers)
            if not identifiers:
                continue
            self.last_family_evaluation_count += 1
            contribution = Decimal(str(base.contribution(event)))
            # Keep zero contributions for correction candidate accounting.
            groups.append((identifiers, contribution))
        return groups

    def _apply(self, identifiers, delta, changed):
        if not delta:
            return
        for identifier in identifiers:
            self._totals[identifier] += delta
            result = CalculationResult(calculation_id=identifier, value=float(self._totals[identifier]),
                                       version=self._results[identifier].version + 1)
            self._results[identifier] = result
            changed.append(result)

    def ingest(self, event: Event) -> list[CalculationResult]:
        self.last_formula_evaluation_count = 0
        self.last_candidate_count = self.last_index_probe_count = 0
        self.last_family_evaluation_count = self.last_time_probe_count = 0
        key = (event.match_id, event.event_id)
        previous = self._events.get(key)
        if previous and event.revision <= previous.revision:
            if event.revision == previous.revision and not event.same_content(previous):
                raise ValueError("Conflicting contents for the same event revision")
            return []
        groups = self._groups(event)
        self._events[key] = event
        changed = []
        if previous is None:
            for identifiers, delta in groups:
                self._apply(identifiers, delta, changed)
        else:
            # Corrections can move across category families and time windows.
            # Net deltas first: an unchanged total must not bump its version.
            deltas = {identifier: delta for identifiers, delta in groups for identifier in identifiers}
            for identifiers, contribution in self._groups(previous):
                for identifier in identifiers:
                    deltas[identifier] = deltas.get(identifier, Decimal(0)) - contribution
            self.last_candidate_count = len(deltas)
            for identifier, delta in deltas.items():
                self._apply((identifier,), delta, changed)
        self._refresh_formulas(changed)
        changed = [result for result in changed if result.calculation_id in self._visible]
        changed.sort(key=lambda result: result.calculation_id)
        return changed
