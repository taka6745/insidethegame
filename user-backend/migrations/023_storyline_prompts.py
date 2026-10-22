"""Storylines (engine stream S3): the match-analyst role and narrative-author v5.

The seeds in migrations/prompts/ were the engine's match-analyst.v1 and narrative-author.v5, byte for byte (kept as
match-analyst.v1.txt and narrative-author.v5.txt since 025 moved the seeds on). A fresh store is seeded at startup
(repositories/prompts.py). In an existing store, match-analyst gets version 1
and narrative-author v5 becomes active even over a /dev/ edit: v5 adds {storylines} and {match_trends}, and the
engine uses a template only when its placeholders equal its shipped file's, so an older author would stop it. Earlier
versions stay, so an edit can be redone on top of v5.
"""
from pathlib import Path

SEEDS = Path(__file__).parent / 'prompts'


def migrate(conn):
    from backend.models.prompts import placeholders
    active = {r['role']: r for r in conn.execute('SELECT a.role, p.placeholders FROM narrative_prompt_active a '
                                                 'JOIN narrative_prompts p USING (role, version)')}
    if not active:
        return  # Fresh store: startup seeds every role as version 1.
    analyst = (SEEDS / 'match-analyst.v1.txt').read_text(encoding='utf-8')
    if 'match-analyst' not in active:
        conn.execute("INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
                     "VALUES ('match-analyst', 1, %s, %s, 'seed') ON CONFLICT DO NOTHING", (analyst, placeholders(analyst)))
        conn.execute("INSERT INTO narrative_prompt_active (role, version, revision) "
                     "SELECT 'match-analyst', 1, max(revision) + 1 FROM narrative_prompt_active")
    author = (SEEDS / 'narrative-author.v5.txt').read_text(encoding='utf-8')
    current = active.get('narrative-author')
    if current is None or current['placeholders'] == placeholders(author):
        return  # Already on v5's placeholders (v5 itself or an edit of it).
    row = conn.execute("SELECT version FROM narrative_prompts WHERE role='narrative-author' AND template=%s",
                       (author,)).fetchone()
    version = row['version'] if row else conn.execute(
        "INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
        "SELECT 'narrative-author', max(version) + 1, %s, %s, 'seed' FROM narrative_prompts "
        "WHERE role='narrative-author' RETURNING version", (author, placeholders(author))).fetchone()['version']
    conn.execute("UPDATE narrative_prompt_active SET version=%s, "
                 "revision=(SELECT max(revision) + 1 FROM narrative_prompt_active) WHERE role='narrative-author'",
                 (version,))
