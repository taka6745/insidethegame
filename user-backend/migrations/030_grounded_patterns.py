"""Live-check fixes (22 Oct): period-end wrap-ups, analyst claim checks and plain-words labels.

- `subscriptions.limits.period_end_wrap_up` (from 024's seed): half and full time give every follow a wrap-up.
- `storyline-policy.claims`: each claim gains `analyst` (also asked of the analyst's observations and resolves) and
  the `comparison` claim is added, from migrations/seeds/storyline-policy.json.
  Keys already present (a /dev/ edit) are kept; a changed row gets a new revision.
- Prompt `match-analyst` v4 (same placeholders as v3): labels and headlines in plain football words, from what each
  indicator measures. Added as the next version; active only while the role still runs an unedited seed.
"""
import importlib.util
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent


def _patch(conn, name, change):
    row = conn.execute('SELECT document FROM backend_config WHERE name = %s', (name,)).fetchone()
    if row is not None and change(row['document']):
        conn.execute('UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = %s',
                     (Jsonb(row['document']), name))


def migrate(conn):
    from backend.models.prompts import placeholders
    claims = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))['claims']
    spec = importlib.util.spec_from_file_location('m024', HERE / '024_subscriptions.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    wrap_up = seed.CONFIG['subscriptions']['limits']['period_end_wrap_up']

    def policy(document):
        stored, changed = document.setdefault('claims', {}), False
        for name, claim in claims.items():
            if name not in stored:
                stored[name], changed = claim, True
            elif 'analyst' not in stored[name]:
                stored[name]['analyst'], changed = claim['analyst'], True
        return changed

    def subscriptions(document):
        limits = document.setdefault('limits', {})
        missing = 'period_end_wrap_up' not in limits
        limits.setdefault('period_end_wrap_up', wrap_up)
        return missing

    _patch(conn, 'storyline-policy', policy)
    _patch(conn, 'subscriptions', subscriptions)

    template = (HERE / 'prompts' / 'match-analyst.txt').read_text(encoding='utf-8')
    active = conn.execute('SELECT p.source, p.placeholders FROM narrative_prompt_active a '
                          "JOIN narrative_prompts p USING (role, version) WHERE role = 'match-analyst'").fetchone()
    if active is None:
        return  # Fresh store: startup seeds the template as version 1.
    if active['placeholders'] != placeholders(template):
        raise RuntimeError('match-analyst v4 changes its placeholders')
    if conn.execute("SELECT 1 FROM narrative_prompts WHERE role = 'match-analyst' AND template = %s",
                    (template,)).fetchone():
        return
    version = conn.execute("INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
                           "SELECT 'match-analyst', max(version) + 1, %s, %s, 'seed' FROM narrative_prompts "
                           "WHERE role = 'match-analyst' RETURNING version",
                           (template, placeholders(template))).fetchone()['version']
    if active['source'] == 'seed':
        conn.execute('UPDATE narrative_prompt_active SET version = %s, revision = (SELECT max(revision) + 1 FROM '
                     "narrative_prompt_active) WHERE role = 'match-analyst'", (version,))
