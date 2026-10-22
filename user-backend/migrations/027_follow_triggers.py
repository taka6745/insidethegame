"""Story-follow triggers (engine stream F2): adds the tunables the engine's trigger pipeline reads to existing rows.

- `subscriptions.limits.pivotal_key_types`: key event types that bypass a topic's minimum gap (decision D4).
- `subscriptions.decision.min_confidence` 0.5 → 0.3 where still the seed: Decision-1 spreads a four-level score's
  probability, so a clear move (a goal for the followed team: score 2.4) came with confidence 0.45 (live, 22 Oct).
- `storyline-policy.claims`: the decision-model questions and thresholds that replace the engine's causal phrase
  list, from migrations/seeds/storyline-policy.json (026 seeds a fresh store with them already).
Keys already present (a /dev/ edit) are kept; a changed row gets a new revision.
"""
import json
from pathlib import Path

from psycopg.types.json import Jsonb

SEED = Path(__file__).parent / 'seeds' / 'storyline-policy.json'
PIVOTAL = ['Goal', 'OwnGoal', 'RedCard', 'PenaltyAwarded', 'PenaltyMissed', 'VarOverturn']


def _patch(conn, name, change):
    row = conn.execute('SELECT document FROM backend_config WHERE name = %s', (name,)).fetchone()
    if row is None:
        return
    document = row['document']
    if change(document):
        conn.execute('UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = %s',
                     (Jsonb(document), name))


def migrate(conn):
    claims = json.loads(SEED.read_text(encoding='utf-8'))['claims']

    def pivotal(document):
        limits = document.setdefault('limits', {})
        changed = limits.setdefault('pivotal_key_types', PIVOTAL) is PIVOTAL
        if document.get('decision', {}).get('min_confidence') == 0.5:
            document['decision']['min_confidence'] = 0.3
            changed = True
        return changed

    def claim_checks(document):
        return document.setdefault('claims', claims) is claims

    _patch(conn, 'subscriptions', pivotal)
    _patch(conn, 'storyline-policy', claim_checks)
