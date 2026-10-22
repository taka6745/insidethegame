"""Clip decision (PLAN.md §10.2 D3/D6): the question asks how relevant a moment is to the followed story, neutrally,
instead of how much followers would want to watch it. Changed only where `subscriptions.clips` still holds the 038
wording and levels; a /dev/ edit of either is kept. A changed row gets a new revision."""
from psycopg.types.json import Jsonb

OLD = {'instructions': "How much would this story's followers want to watch this moment as a clip?",
       'levels': ['Not at all', 'A little', 'Quite a lot', 'They would want to see it']}
NEW = {'instructions': 'How relevant is this moment to the story these viewers follow?',
       'levels': ['Not relevant', 'Slightly relevant', 'Relevant', 'Central to the story']}


def migrate(conn):
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()
    clips = (row or {}).get('document', {}).get('clips') if row else None
    if not clips or any(clips.get(key) != value for key, value in OLD.items()):
        return
    conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'subscriptions'",
                 (Jsonb({**row['document'], 'clips': {**clips, **NEW}}),))
