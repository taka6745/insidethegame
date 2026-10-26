"""`narrative-author` v8: the per-bucket segments (`{user_type}`, `{narrative_excerpts}`) move to the tail so the
buckets of a step share a prompt prefix long enough for the model API's prompt cache (same placeholders, same
wording). Active over the unedited seed only; a /dev/ edit stays. A fresh store gets it at startup."""
from pathlib import Path

HERE = Path(__file__).parent


def migrate(conn):
    from backend.models.prompts import placeholders
    role = 'narrative-author'
    active = conn.execute('SELECT a.version, p.source, p.placeholders FROM narrative_prompt_active a '
                          'JOIN narrative_prompts p USING (role, version) WHERE role = %s', (role,)).fetchone()
    if active is None:
        return  # Fresh store: startup seeds the template as version 1.
    template = (HERE / 'prompts' / f'{role}.txt').read_text(encoding='utf-8')
    wanted = placeholders(template)
    if active['placeholders'] != wanted:
        raise RuntimeError(f'{role} v8 changes its placeholders')
    if active['source'] != 'seed':
        return
    row = conn.execute('SELECT version FROM narrative_prompts WHERE role = %s AND template = %s',
                       (role, template)).fetchone()
    version = row['version'] if row else conn.execute(
        "INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
        "SELECT %s, max(version) + 1, %s, %s, 'seed' FROM narrative_prompts WHERE role = %s RETURNING version",
        (role, template, wanted, role)).fetchone()['version']
    if version != active['version']:
        conn.execute('UPDATE narrative_prompt_active SET version = %s, '
                     'revision = (SELECT max(revision) + 1 FROM narrative_prompt_active) WHERE role = %s',
                     (version, role))
