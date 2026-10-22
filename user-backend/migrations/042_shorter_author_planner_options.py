"""Developer review of the local demo (22 Oct): shorter insights, and follow-chat drill-in choices.

- `narrative-author`: one or two short sentences citing at most the one or two numbers that carry the point
  (same placeholders). It becomes active only over the shipped seed; a /dev/ edit stays active.
- `subscription-planner` v2: sees the matches being played now (`{live_matches}`), labels name the viewer's focus,
  and a clarification carries up to four `options` resolved by code (services/subscriptions). New placeholders, so
  it becomes active even over a /dev/ edit (as in 023 and 029); the edit stays as a version to redo on top.
A fresh store gets both at startup (repositories/prompts.py)."""
from pathlib import Path

HERE = Path(__file__).parent


def _version(conn, role, template, placeholders):
    row = conn.execute('SELECT version FROM narrative_prompts WHERE role=%s AND template=%s',
                       (role, template)).fetchone()
    return row['version'] if row else conn.execute(
        "INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
        "SELECT %s, max(version) + 1, %s, %s, 'seed' FROM narrative_prompts WHERE role=%s RETURNING version",
        (role, template, placeholders, role)).fetchone()['version']


def migrate(conn):
    from backend.models.prompts import placeholders
    for role in ('narrative-author', 'subscription-planner'):
        active = conn.execute('SELECT a.version, p.source, p.placeholders FROM narrative_prompt_active a '
                              'JOIN narrative_prompts p USING (role, version) WHERE role = %s', (role,)).fetchone()
        if active is None:
            continue  # Fresh store: startup seeds the template as version 1.
        template = (HERE / 'prompts' / f'{role}.txt').read_text(encoding='utf-8')
        wanted = placeholders(template)
        if active['source'] != 'seed' and active['placeholders'] == wanted:
            continue  # A /dev/ edit on the same placeholders stays active.
        version = _version(conn, role, template, wanted)
        if version != active['version']:
            conn.execute('UPDATE narrative_prompt_active SET version=%s, '
                         'revision=(SELECT max(revision) + 1 FROM narrative_prompt_active) WHERE role=%s',
                         (version, role))
