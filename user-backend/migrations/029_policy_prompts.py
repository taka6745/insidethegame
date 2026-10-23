"""Tunables out of code and no viewer text in the shared follow state.

- `storyline-policy.claims.result`: the decision-model question that replaces the engine's result phrase list
  (from migrations/seeds/storyline-policy.json; 026 seeds a fresh store with it already).
- `subscriptions.limits.planner_context_turns` (the follow-chat turns the planner sees) and `subscriptions.catch_up`
  (the "story so far" step's trigger reason), from 024's seed.
  Keys already present (a /dev/ edit) are kept; a changed row gets a new revision.
- Prompts `match-analyst` v3 (its limits are placeholders filled from the storyline policy) and
  `subscription-decision` v2 (no `{follows}` block: viewer text goes only in each topic's own questions). Both
  change their role's placeholders, and the engine uses a template only when its placeholders equal its shipped
  file's, so each becomes active even over a /dev/ edit (as in 023); the edit stays as a version to redo on top.
"""
import importlib.util
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent
ROLES = ('match-analyst', 'subscription-decision')
FILES = {'match-analyst': 'match-analyst.v3.txt'}  # analyst v4 (same placeholders): 030


def _patch(conn, name, change):
    row = conn.execute('SELECT document FROM backend_config WHERE name = %s', (name,)).fetchone()
    if row is not None and change(row['document']):
        conn.execute('UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = %s',
                     (Jsonb(row['document']), name))


def migrate(conn):
    from backend.models.prompts import placeholders
    result = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))['claims']['result']
    spec = importlib.util.spec_from_file_location('m024', HERE / '024_subscriptions.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    follows = seed.CONFIG['subscriptions']

    def add(section, key, value):
        """Set a missing key (a present one may be a /dev/ edit); True if it was missing."""
        missing = key not in section
        section.setdefault(key, value)
        return missing

    def claims(document):
        return add(document.setdefault('claims', {}), 'result', result)

    def subscriptions(document):
        turns = add(document.setdefault('limits', {}), 'planner_context_turns',
                    follows['limits']['planner_context_turns'])
        return add(document, 'catch_up', follows['catch_up']) | turns

    _patch(conn, 'storyline-policy', claims)
    _patch(conn, 'subscriptions', subscriptions)

    active = {r['role']: r for r in conn.execute('SELECT a.role, p.placeholders FROM narrative_prompt_active a '
                                                 'JOIN narrative_prompts p USING (role, version)')}
    for role in ROLES:
        if role not in active:
            continue  # Fresh store: startup seeds these templates as version 1.
        template = (HERE / 'prompts' / FILES.get(role, f'{role}.txt')).read_text(encoding='utf-8')
        if active[role]['placeholders'] == placeholders(template):
            continue  # Already on the new placeholders.
        row = conn.execute('SELECT version FROM narrative_prompts WHERE role=%s AND template=%s',
                           (role, template)).fetchone()
        version = row['version'] if row else conn.execute(
            "INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
            "SELECT %s, max(version) + 1, %s, %s, 'seed' FROM narrative_prompts WHERE role=%s RETURNING version",
            (role, template, placeholders(template), role)).fetchone()['version']
        conn.execute('UPDATE narrative_prompt_active SET version=%s, '
                     'revision=(SELECT max(revision) + 1 FROM narrative_prompt_active) WHERE role=%s', (version, role))
