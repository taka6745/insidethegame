"""Neutral example teams: `minute-summary` and `context-compression` examples name "Team A"/"Team B" and
no player, instead of real clubs (older seeds) or clubs that play in the demo. Where the active template's examples
still name one of those, a new version swaps in the seed's examples (the rest of a /dev/ edit is kept, as is its
source) and becomes active; the old one stays as a version. A fresh store gets the seeds at startup."""
import re
from pathlib import Path

HERE = Path(__file__).parent
EXAMPLES = re.compile(r'Some examples of a good summary include:\n.*?\n\n', re.S)
RETIRED = ('Liverpool', 'Manchester United', 'Lammens', 'Forgeham United', 'Port Albion', 'Halloran')


def migrate(conn):
    for role in ('minute-summary', 'context-compression'):
        active = conn.execute('SELECT p.template, p.placeholders, p.source FROM narrative_prompt_active a '
                              'JOIN narrative_prompts p USING (role, version) WHERE role = %s', (role,)).fetchone()
        found = active and EXAMPLES.search(active['template'])
        if not found or not any(name in found.group(0) for name in RETIRED):
            continue
        seed = EXAMPLES.search((HERE / 'prompts' / f'{role}.txt').read_text(encoding='utf-8')).group(0)
        template = active['template'].replace(found.group(0), seed)
        row = conn.execute('SELECT version FROM narrative_prompts WHERE role = %s AND template = %s',
                           (role, template)).fetchone()
        version = row['version'] if row else conn.execute(
            'INSERT INTO narrative_prompts (role, version, template, placeholders, source) '
            'SELECT %s, max(version) + 1, %s, %s, %s FROM narrative_prompts WHERE role = %s RETURNING version',
            (role, template, active['placeholders'], active['source'], role)).fetchone()['version']
        conn.execute('UPDATE narrative_prompt_active SET version = %s, '
                     'revision = (SELECT max(revision) + 1 FROM narrative_prompt_active) WHERE role = %s',
                     (version, role))
