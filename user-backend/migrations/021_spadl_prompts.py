"""Narrative prompts gain the SPADL glossary (narrative-author v4, minute-summary v2; engine stream S3).

The seeds in migrations/prompts/ were those templates, byte for byte, with unchanged placeholders (the author's
is kept as narrative-author.v4.txt since 023 moved its seed to v5).
A fresh store is seeded with them at startup (repositories/prompts.py). An existing store gets each as
its next version; it becomes active only while the role still runs an unedited seed, so /dev/ edits stay.
"""
from pathlib import Path

SEEDS = Path(__file__).parent / 'prompts'


def migrate(conn):
    from backend.models.prompts import placeholders
    for role in ('narrative-author', 'minute-summary'):
        # The author's SPADL version is v4; its seed has since moved on (023), so read the v4 copy.
        template = (SEEDS / ('narrative-author.v4.txt' if role == 'narrative-author' else f'{role}.txt')).read_text(
            encoding='utf-8')
        active = conn.execute('SELECT p.version, p.source, p.placeholders FROM narrative_prompt_active a '
                              'JOIN narrative_prompts p USING (role, version) WHERE role=%s', (role,)).fetchone()
        if active is None:
            continue  # Fresh store: startup seeds these templates as version 1.
        if active['placeholders'] != placeholders(template):
            raise RuntimeError(f'SPADL {role} prompt changes its placeholders')
        if conn.execute('SELECT 1 FROM narrative_prompts WHERE role=%s AND template=%s', (role, template)).fetchone():
            continue
        version = conn.execute("INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
                               "SELECT %s, max(version) + 1, %s, %s, 'seed' FROM narrative_prompts WHERE role=%s "
                               'RETURNING version', (role, template, placeholders(template), role)).fetchone()['version']
        if active['source'] == 'seed':
            conn.execute('UPDATE narrative_prompt_active SET version=%s, '
                         'revision=(SELECT max(revision) + 1 FROM narrative_prompt_active) WHERE role=%s', (version, role))
