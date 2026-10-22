"""Demo build D3/D4 (2026-10-22): replay playback settings, served with every replay.

`replay-timing.playback` holds the clip transitions (hold the last frame, then the sting video fades in over
the cut and fades out; the asset path is config, see frontend/assets/league/PROVENANCE.md) and
slow motion around each clip's marked events. Both have an `enabled` flag; the viewer skips both under
prefers-reduced-motion. A `playback` key already present (a /dev/ edit) is kept.
"""
from psycopg.types.json import Jsonb

PLAYBACK = {
    'transitions': {'enabled': True, 'hold_seconds': 0.6, 'asset': '/assets/league/sting/replay-sting.mp4',
                    'asset_start_seconds': 0.3, 'sting_seconds': 2.4, 'cut_seconds': 0.5, 'fade_seconds': 0.3},
    'slow_motion': {'enabled': True, 'rate': 0.5, 'ramp_seconds': 0.6, 'before_seconds': 1.0, 'after_seconds': 1.5},
}


def migrate(conn):
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'replay-timing'").fetchone()
    if row is None or 'playback' in row['document']:
        return
    conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'replay-timing'",
                 (Jsonb({**row['document'], 'playback': PLAYBACK}),))
