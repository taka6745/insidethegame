"""Fictional league: the clip transition becomes the league's own CSS sting (`builtin:league`)
instead of the third-party video. Changed only where `replay-timing.playback.transitions.asset` still holds the
037 path; a /dev/ edit is kept. A changed row gets a new revision."""
from psycopg.types.json import Jsonb

OLD = '/assets/league/sting/replay-sting.mp4'
NEW = 'builtin:league'


def migrate(conn):
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'replay-timing'").fetchone()
    transitions = (row['document'].get('playback') or {}).get('transitions') if row else None
    if not transitions or transitions.get('asset') != OLD:
        return
    playback = {**row['document']['playback'], 'transitions': {**transitions, 'asset': NEW}}
    conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'replay-timing'",
                 (Jsonb({**row['document'], 'playback': playback}),))
