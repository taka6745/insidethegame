"""Follow clips arrive as their own engine message (`FollowClip`), not on a follow narrative: a clip is a fact about
the moment, so a narrative dropped as ungrounded no longer loses it. `subscription_clips.narrative_id` becomes
`step_id`, the follow step whose decision judged the moment worth a clip.
"""


def migrate(conn):
    if conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND table_name = 'subscription_clips' AND column_name = 'narrative_id'").fetchone():
        conn.execute('ALTER TABLE subscription_clips RENAME COLUMN narrative_id TO step_id')
