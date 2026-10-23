"""Grounded storylines: match-analyst v2 and narrative-author v6.

The seeds in migrations/prompts/ are those templates (the analyst's kept as match-analyst.v2.txt since 029), byte for byte, with unchanged placeholders. The analyst reads a
side-by-side trend table and gives confidence as a level ("low", "medium", "high"); the author's prompt describes
the trend units and drops its example excerpt. Grounding itself is checked in the engine. A fresh store is seeded with them at startup. An existing store gets each as its
next version; it becomes active only while the role still runs an unedited seed, so /dev/ edits stay.
"""
from pathlib import Path

SEEDS = Path(__file__).parent / 'prompts'
FILES = {'match-analyst': 'match-analyst.v2.txt', 'narrative-author': 'narrative-author.txt'}  # analyst v3: 029


def migrate(conn):
    from backend.models.prompts import placeholders
    for role in ('match-analyst', 'narrative-author'):
        template = (SEEDS / FILES[role]).read_text(encoding='utf-8')
        active = conn.execute('SELECT p.source, p.placeholders FROM narrative_prompt_active a '
                              'JOIN narrative_prompts p USING (role, version) WHERE role=%s', (role,)).fetchone()
        if active is None:
            continue  # Fresh store: startup seeds these templates as version 1.
        if active['placeholders'] != placeholders(template):
            raise RuntimeError(f'grounded {role} prompt changes its placeholders')
        if conn.execute('SELECT 1 FROM narrative_prompts WHERE role=%s AND template=%s', (role, template)).fetchone():
            continue
        version = conn.execute("INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
                               "SELECT %s, max(version) + 1, %s, %s, 'seed' FROM narrative_prompts WHERE role=%s "
                               'RETURNING version', (role, template, placeholders(template), role)).fetchone()['version']
        if active['source'] == 'seed':
            conn.execute('UPDATE narrative_prompt_active SET version=%s, '
                         'revision=(SELECT max(revision) + 1 FROM narrative_prompt_active) WHERE role=%s', (version, role))
