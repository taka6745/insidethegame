"""Versioned migrations on real Postgres: an old deployment's orphaned narrative tables are dropped."""
from psycopg import sql

ORPHANS = ('narrative_framing_leases', 'narrative_variants', 'neutral_narratives')


def tables(store):
    with store.connect() as conn:
        return {row['table_name'] for row in conn.execute(
            'SELECT table_name FROM information_schema.tables WHERE table_schema = %s', (store.schema,))}


def test_orphaned_narrative_tables_are_dropped_once_and_nothing_else(store):
    with store.connect() as conn:
        # The retired cache as an older deployment left it, including its internal foreign key.
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(store.schema)))
        conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(store.schema)))
        conn.execute('CREATE TABLE neutral_narratives (match_id text, narrative_id text, revision int, text text, '
                     'PRIMARY KEY (match_id, narrative_id, revision))')
        conn.execute('CREATE TABLE narrative_variants (match_id text, narrative_id text, revision int, bucket_id text, '
                     'FOREIGN KEY (match_id, narrative_id, revision) REFERENCES neutral_narratives)')
        conn.execute('CREATE TABLE narrative_framing_leases (match_id text, narrative_id text)')
        conn.execute("INSERT INTO neutral_narratives VALUES ('m', 'n', 1, 'Old.')")
        conn.execute("INSERT INTO narrative_variants VALUES ('m', 'n', 1, 'home:simple')")
    store.initialize()
    found = tables(store)
    assert not found & set(ORPHANS)
    assert {'received_matches', 'received_events', 'engine_narratives', 'audience_templates', 'audience_catalog',
            'backend_config', 'narrative_prompts', 'match_tombstones', 'question_turns', 'match_gaps'} <= found
    with store.connect() as conn:
        applied = [row['version'] for row in conn.execute('SELECT version FROM schema_migrations ORDER BY version')]
        config = conn.execute('SELECT name, revision FROM backend_config ORDER BY name').fetchall()
    assert applied[-20:] == ['024_subscriptions.py', '025_grounded_prompts.py',
                             '026_storyline_policy.py', '027_follow_triggers.py', '028_key_moment_labels.py',
                             '029_policy_prompts.py', '030_grounded_patterns.py', '031_policy_limits.py',
                             '032_follow_retries.py', '033_comparison_claim.py', '034_result_claim.py',
                             '035_author_trim.py', '036_score_claim_reopen.py', '037_replay_playback.py',
                             '038_follow_clips.py', '039_follow_clip_step.py',
                             '040_cross_match.py', '041_capture_clips.py', '042_shorter_author_planner_options.py',
                             '043_narrative_clips_match.sql']
    store.initialize()  # Applied once: a restart changes nothing.
    assert tables(store) == found
    with store.connect() as conn:
        assert conn.execute('SELECT name, revision FROM backend_config ORDER BY name').fetchall() == config


def test_pins_become_enabled_flags_and_presence_columns_go(store):
    from psycopg.types.json import Jsonb
    from backend.store import MIGRATIONS, migrate
    with store.connect() as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(store.schema)))
        conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(store.schema)))
        migrate(conn, [p for p in sorted(MIGRATIONS.glob('*.sql')) if p.name < '018'])
        default = conn.execute("SELECT document FROM audience_templates WHERE fixture='default'").fetchone()['document']
        conn.execute("INSERT INTO audience_templates (fixture, revision, document, pinned_buckets) "
                     "VALUES ('chelsea-united', 4, %s, ARRAY['away:simple'])", (Jsonb(default),))
        conn.execute("INSERT INTO received_matches (match_id, fixture, sent_at) VALUES ('chelsea-united-1', 'chelsea-united', now())")
        conn.execute("INSERT INTO audience_catalog (match_id, fixture, document, viewer_counts) "
                     "VALUES ('chelsea-united-1', 'chelsea-united', %s, '{\"home:simple\": 2}')", (Jsonb(default),))
    store.initialize()
    with store.connect() as conn:
        rows = {r['fixture']: r for r in conn.execute('SELECT * FROM audience_templates')}
        catalog = conn.execute('SELECT * FROM audience_catalog').fetchone()
    on = lambda document: {b['id'] for b in document['buckets'] if b['enabled']}
    assert on(rows['chelsea-united']['document']) == {'away:simple'} and rows['chelsea-united']['revision'] == 5
    # The unedited default enables the demo profiles' buckets.
    assert on(rows['default']['document']) == {'home:analytical', 'away:casual', 'neutral:simple'}
    assert 'pinned_buckets' not in rows['default'] and 'viewer_counts' not in catalog
    assert catalog['document'] == rows['chelsea-united']['document'] and catalog['revision'] == 2
    labels = [[o['label'] for o in layer['options']] for layer in rows['default']['document']['layers']]
    assert labels == [['{home}', '{away}', 'Neutral'], ['Simple', 'Casual', 'Experienced', 'Analytical']]


def test_follow_trigger_tunables_are_added_to_existing_rows_and_edits_are_kept(store):
    import json
    from psycopg.types.json import Jsonb
    from backend.store import MIGRATIONS
    store.initialize()
    seed = json.loads((MIGRATIONS / 'seeds' / 'storyline-policy.json').read_text())
    with store.connect() as conn:
        fresh = {r['name']: r['revision'] for r in conn.execute('SELECT name, revision FROM backend_config')}
        assert (fresh['subscriptions'], fresh['storyline-policy']) == (1, 1)  # a fresh store is seeded complete
        subs = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()['document']
        policy = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'").fetchone()['document']
        assert subs['limits']['pivotal_key_types'] and policy['claims'] == seed['claims']
        # A store from before 027: no pivotal types, no claims (an edited claims section would be kept).
        del subs['limits']['pivotal_key_types']
        subs['decision']['min_confidence'] = 0.5  # the earlier seed
        del policy['claims']
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'", (Jsonb(subs),))
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '027_follow_triggers.py'")
    store.initialize()
    with store.connect() as conn:
        rows = {r['name']: r for r in conn.execute('SELECT name, revision, document FROM backend_config')}
    assert rows['subscriptions']['document']['limits']['pivotal_key_types'] == [
        'Goal', 'OwnGoal', 'RedCard', 'PenaltyAwarded', 'PenaltyMissed', 'VarOverturn']
    assert rows['storyline-policy']['document']['claims'] == seed['claims']
    assert rows['subscriptions']['document']['decision']['min_confidence'] == 0.3
    assert rows['subscriptions']['revision'] == rows['storyline-policy']['revision'] == 2


def test_key_moment_labels_take_the_new_wording_where_still_the_seed(store):
    from psycopg.types.json import Jsonb
    store.initialize()
    with store.connect() as conn:
        fresh = conn.execute("SELECT revision, document FROM backend_config WHERE name = 'key-moment-feed'").fetchone()
        assert fresh['revision'] == 1 and fresh['document']['labels']['goal'] == 'Goal · {team} · {scorer}'
        old = fresh['document']
        old['labels'] |= {'goal': 'Goal · {subject}', 'red_card': 'My red · {subject}', 'half_time': 'Half-time'}
        del old['score']  # a store from before 028, with one /dev/ edit
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'key-moment-feed'", (Jsonb(old),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '028_key_moment_labels.py'")
    store.initialize()
    with store.connect() as conn:
        row = conn.execute("SELECT revision, document FROM backend_config WHERE name = 'key-moment-feed'").fetchone()
    labels = row['document']['labels']
    assert (labels['goal'], labels['red_card'], labels['half_time']) == (
        'Goal · {team} · {scorer}', 'My red · {subject}', 'Half time · {score}')
    assert row['document']['score'] == '{home} {home_goals}–{away_goals} {away}' and row['revision'] == 2


def test_policy_tunables_and_prompts_reach_existing_stores_and_edits_are_kept(store):
    import json
    from psycopg.types.json import Jsonb
    from backend.models.prompts import placeholders
    from backend.store import MIGRATIONS
    store.initialize()
    seeds = MIGRATIONS / 'prompts'
    result = json.loads((MIGRATIONS / 'seeds' / 'storyline-policy.json').read_text())['claims']['result']
    with store.connect() as conn:
        fresh = {r['name']: r for r in conn.execute('SELECT name, revision, document FROM backend_config')}
        assert (fresh['subscriptions']['revision'], fresh['storyline-policy']['revision']) == (1, 1)
        assert fresh['storyline-policy']['document']['claims']['result'] == result
        subs, policy = fresh['subscriptions']['document'], fresh['storyline-policy']['document']
        # A store from before 029: no result claim, catch-up reason or planner turns; one /dev/ edit of each kind.
        del policy['claims']['result'], subs['catch_up'], subs['limits']['planner_context_turns']
        policy['claims']['causal']['min_claim_probability'] = 0.7
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'", (Jsonb(subs),))
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
        conn.execute('DELETE FROM narrative_prompt_active')
        conn.execute('DELETE FROM narrative_prompts')
        old = {'match-analyst': (seeds / 'match-analyst.v2.txt').read_text() + '\nAn edit.',
               'subscription-decision': (seeds / 'subscription-decision.v1.txt').read_text()}
        for role, template in old.items():
            conn.execute("INSERT INTO narrative_prompts VALUES (%s, 1, %s, %s, 'dev', now())",
                         (role, template, placeholders(template)))
            conn.execute('INSERT INTO narrative_prompt_active VALUES (%s, 1, 1)', (role,))
        conn.execute("DELETE FROM schema_migrations WHERE version = '029_policy_prompts.py'")
    store.initialize()
    with store.connect() as conn:
        rows = {r['name']: r for r in conn.execute('SELECT name, revision, document FROM backend_config')}
        active = {r['role']: r for r in conn.execute('SELECT a.role, a.version, p.template FROM narrative_prompt_active '
                                                     'a JOIN narrative_prompts p USING (role, version)')}
        kept = conn.execute("SELECT template FROM narrative_prompts WHERE role='match-analyst' AND version=1")
        assert kept.fetchone()['template'] == old['match-analyst']  # the edit stays as a version
    claims = rows['storyline-policy']['document']['claims']
    assert claims['result'] == result and claims['causal']['min_claim_probability'] == 0.7
    subs = rows['subscriptions']['document']
    assert subs['limits']['planner_context_turns'] == 6 and subs['catch_up']['reason']
    assert rows['subscriptions']['revision'] == rows['storyline-policy']['revision'] == 2
    files = {'match-analyst': 'match-analyst.v3.txt'}  # 030 moves an unedited seed on to v4
    for role in old:  # new placeholders: the engine would refuse the old set, so the seed becomes active
        assert (active[role]['version'], active[role]['template']) == (2, (seeds / files.get(role, f'{role}.txt')).read_text())


def test_wrap_ups_claims_and_analyst_v4_reach_existing_stores_and_edits_are_kept(store):
    import json
    from psycopg.types.json import Jsonb
    from backend.models.prompts import placeholders
    from backend.store import MIGRATIONS
    store.initialize()
    seed = json.loads((MIGRATIONS / 'seeds' / 'storyline-policy.json').read_text())['claims']
    v3 = (MIGRATIONS / 'prompts' / 'match-analyst.v3.txt').read_text()
    with store.connect() as conn:
        fresh = {r['name']: r['document'] for r in conn.execute('SELECT name, document FROM backend_config')}
        assert fresh['storyline-policy']['claims'] == seed and fresh['subscriptions']['limits']['period_end_wrap_up']
        policy, subs = fresh['storyline-policy'], fresh['subscriptions']
        # A store from before 030, with a /dev/ edit of the causal claim and analyst v3 as its unedited seed.
        del policy['claims']['comparison'], subs['limits']['period_end_wrap_up']
        for claim in policy['claims'].values():
            del claim['analyst']
        policy['claims']['causal']['min_claim_probability'] = 0.7
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'", (Jsonb(subs),))
        conn.execute("DELETE FROM narrative_prompt_active WHERE role = 'match-analyst'")
        conn.execute("DELETE FROM narrative_prompts WHERE role = 'match-analyst'")
        conn.execute("INSERT INTO narrative_prompts VALUES ('match-analyst', 1, %s, %s, 'seed', now())",
                     (v3, placeholders(v3)))
        conn.execute("INSERT INTO narrative_prompt_active VALUES ('match-analyst', 1, 1)")
        conn.execute("DELETE FROM schema_migrations WHERE version = '030_grounded_patterns.py'")
    store.initialize()
    with store.connect() as conn:
        rows = {r['name']: r['document'] for r in conn.execute('SELECT name, document FROM backend_config')}
        active = conn.execute("SELECT p.version, p.template FROM narrative_prompt_active a JOIN narrative_prompts p "
                              "USING (role, version) WHERE role = 'match-analyst'").fetchone()
    claims = rows['storyline-policy']['claims']
    assert claims['comparison'] == seed['comparison'] and claims['causal']['min_claim_probability'] == 0.7
    assert {n: c['analyst'] for n, c in claims.items()} == {n: c['analyst'] for n, c in seed.items()}
    assert rows['subscriptions']['limits']['period_end_wrap_up'] is True
    assert active['template'] == (MIGRATIONS / 'prompts' / 'match-analyst.txt').read_text() and active['version'] == 2


def test_policy_limits_reach_existing_stores_and_edits_are_kept(store):
    import json
    from psycopg.types.json import Jsonb
    from backend.store import MIGRATIONS
    store.initialize()
    seed = json.loads((MIGRATIONS / 'seeds' / 'storyline-policy.json').read_text())['storylines']
    with store.connect() as conn:
        rows = {r['name']: r['document'] for r in conn.execute('SELECT name, document FROM backend_config')}
        policy, subs = rows['storyline-policy'], rows['subscriptions']
        assert policy['storylines']['beats_shown'] == seed['beats_shown'] and subs['max_candidates'] == 4
        # A store from before 031, with a /dev/ edit of one new key already made.
        del policy['storylines']['resolved_shown_minutes'], policy['storylines']['author_match_indicators']
        policy['storylines']['beats_shown'] = 2
        del subs['max_candidates']
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'", (Jsonb(subs),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '031_policy_limits.py'")
    store.initialize()
    with store.connect() as conn:
        rows = {r['name']: r['document'] for r in conn.execute('SELECT name, document FROM backend_config')}
    lines = rows['storyline-policy']['storylines']
    assert lines['beats_shown'] == 2 and lines['resolved_shown_minutes'] == seed['resolved_shown_minutes']
    assert lines['author_match_indicators'] == seed['author_match_indicators']
    assert rows['subscriptions']['max_candidates'] == 4


def test_follow_retries_and_analyst_intent_reach_existing_stores(store):
    from psycopg.types.json import Jsonb
    store.initialize()
    with store.connect() as conn:
        rows = {r['name']: r['document'] for r in conn.execute('SELECT name, document FROM backend_config')}
        policy, subs = rows['storyline-policy'], rows['subscriptions']
        assert subs['catch_up']['retries'] == 2 and policy['claims']['intent']['analyst'] is True
        # A store from before 032: no retries, the intent claim as 030 seeded it.
        del subs['catch_up']['retries']
        policy['claims']['intent']['analyst'] = False
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'", (Jsonb(subs),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '032_follow_retries.py'")
    store.initialize()
    with store.connect() as conn:
        rows = {r['name']: r['document'] for r in conn.execute('SELECT name, document FROM backend_config')}
        assert rows['subscriptions']['catch_up']['retries'] == 2
        assert rows['storyline-policy']['claims']['intent']['analyst'] is True
        # An edited intent claim is kept as edited.
        policy = rows['storyline-policy']
        policy['claims']['intent'] |= {'analyst': False, 'min_claim_probability': 0.7}
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '032_follow_retries.py'")
    store.initialize()
    with store.connect() as conn:
        doc = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'").fetchone()
    assert doc['document']['claims']['intent']['analyst'] is False



def test_follow_clips_reach_existing_stores_and_keep_edits(store):
    from psycopg.types.json import Jsonb
    store.initialize()
    with store.connect() as conn:
        subs = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()['document']
        assert subs['clips']['enabled'] and subs['clips']['timing']['goal'] == 'goal'
        assert conn.execute("SELECT to_regclass('subscription_clips') AS t").fetchone()['t']
        del subs['clips']  # a store from before 038
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'", (Jsonb(subs),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '038_follow_clips.py'")
    store.initialize()
    with store.connect() as conn:
        subs = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()['document']
        assert subs['clips']['min_level'] == 3
        subs['clips']['min_level'] = 2  # a /dev/ edit
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'", (Jsonb(subs),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '038_follow_clips.py'")
    store.initialize()
    with store.connect() as conn:
        subs = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()['document']
    assert subs['clips']['min_level'] == 2
    with store.connect() as conn:  # 039: the clip names its follow step
        columns = {r['column_name'] for r in conn.execute("SELECT column_name FROM information_schema.columns "
                                                           "WHERE table_name = 'subscription_clips'")}
    assert 'step_id' in columns and 'narrative_id' not in columns


def test_capture_clip_settings_reach_existing_stores_and_keep_edits(store):
    from psycopg.types.json import Jsonb
    store.initialize()
    with store.connect() as conn:
        assert conn.execute("SELECT to_regclass('narrative_clips') AS t").fetchone()['t']
        subs = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()['document']
        assert subs['clips']['always_for'] == [] and subs['clips']['shared'] is True
        clips = {k: v for k, v in subs['clips'].items() if k not in ('always_for', 'shared')}  # a store before 041
        conn.execute("UPDATE backend_config SET document = %s WHERE name = 'subscriptions'",
                     (Jsonb({**subs, 'clips': {**clips, 'max_items': 5}}),))
        conn.execute("DELETE FROM schema_migrations WHERE version = '041_capture_clips.py'")
    store.initialize()
    with store.connect() as conn:
        clips = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'"
                             ).fetchone()['document']['clips']
        assert clips['shared'] is True and clips['always_for'] == [] and clips['max_items'] == 5  # the edit kept
        conn.execute("UPDATE backend_config SET document = jsonb_set(document, '{clips,shared}', 'false') "
                     "WHERE name = 'subscriptions'")  # a /dev/ edit
        conn.execute("DELETE FROM schema_migrations WHERE version = '041_capture_clips.py'")
    store.initialize()
    with store.connect() as conn:
        clips = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'"
                             ).fetchone()['document']['clips']
    assert clips['shared'] is False


def test_comparison_claim_reaches_unedited_stores(store):
    import importlib.util
    import json
    from psycopg.types.json import Jsonb
    from backend.store import MIGRATIONS
    spec = importlib.util.spec_from_file_location('m033', MIGRATIONS / '033_comparison_claim.py')
    m033 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m033)
    seed = json.loads((MIGRATIONS / 'seeds' / 'storyline-policy.json').read_text())['claims']['comparison']
    store.initialize()
    for edit, expected in (({}, seed), ({'min_claim_probability': 0.7, 'support': 'Edited?'}, None)):
        with store.connect() as conn:
            policy = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                  ).fetchone()['document']
            # A store from before 033: the comparison claim as 030 seeded it, maybe edited since.
            policy['claims']['comparison'] |= m033.SEEDED_030 | edit
            before = dict(policy['claims']['comparison'])
            conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
            conn.execute("DELETE FROM schema_migrations WHERE version = '033_comparison_claim.py'")
        store.initialize()
        with store.connect() as conn:
            claim = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                 ).fetchone()['document']['claims']['comparison']
        assert claim == (expected or before)


def test_result_claim_reaches_unedited_stores(store):
    """034: a half-time score is not how the match ended; an edited result claim is kept."""
    import importlib.util
    import json
    from psycopg.types.json import Jsonb
    from backend.store import MIGRATIONS
    spec = importlib.util.spec_from_file_location('m034', MIGRATIONS / '034_result_claim.py')
    m034 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m034)
    seed = json.loads((MIGRATIONS / 'seeds' / 'storyline-policy.json').read_text())['claims']['result']
    assert 'half-time' in seed['claim']
    store.initialize()
    for old, expected in ((m034.SEEDED_030, seed['claim']), ('Edited?', 'Edited?')):
        with store.connect() as conn:
            policy = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                  ).fetchone()['document']
            policy['claims']['result']['claim'] = old
            conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
            conn.execute("DELETE FROM schema_migrations WHERE version = '034_result_claim.py'")
        store.initialize()
        with store.connect() as conn:
            claim = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                 ).fetchone()['document']['claims']['result']
        assert claim['claim'] == expected


def test_author_trim_is_added_once_and_an_edit_is_kept(store):
    store.initialize()
    from psycopg.types.json import Jsonb
    for present, expected in ((None, True), (False, False)):
        with store.connect() as conn:
            policy = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                  ).fetchone()['document']
            policy['repair'].pop('author_trim', None)
            if present is not None:
                policy['repair']['author_trim'] = present
            conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
            conn.execute("DELETE FROM schema_migrations WHERE version = '035_author_trim.py'")
        store.initialize()
        with store.connect() as conn:
            repair = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                  ).fetchone()['document']['repair']
        assert repair['author_trim'] is expected


def test_score_claim_and_reopen_window_are_added_once_and_edits_are_kept(store):
    store.initialize()
    from psycopg.types.json import Jsonb
    for edited in (False, True):
        with store.connect() as conn:
            policy = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                  ).fetchone()['document']
            policy['storylines'].pop('reopen_within', None)
            policy['claims'].pop('score', None)
            if edited:
                policy['storylines']['reopen_within'] = 3
                policy['claims']['score'] = {'enabled': False}
            conn.execute("UPDATE backend_config SET document = %s WHERE name = 'storyline-policy'", (Jsonb(policy),))
            conn.execute("DELETE FROM schema_migrations WHERE version = '036_score_claim_reopen.py'")
        store.initialize()
        with store.connect() as conn:
            policy = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'"
                                  ).fetchone()['document']
        assert policy['storylines']['reopen_within'] == (3 if edited else 15)
        assert policy['claims']['score']['enabled'] is (not edited)


def test_replay_playback_is_added_once_valid_and_an_edit_is_kept(store):
    store.initialize()
    from psycopg.types.json import Jsonb
    from backend.models.config import Replay
    with store.connect() as conn:
        document = conn.execute("SELECT document FROM backend_config WHERE name = 'replay-timing'").fetchone()['document']
    seeded = Replay.model_validate(document).playback
    assert seeded.transitions.enabled and seeded.slow_motion.enabled
    assert seeded.transitions.asset == '/assets/league/sting/replay-sting.mp4'
    edited = {**document['playback'], 'slow_motion': {**document['playback']['slow_motion'], 'enabled': False}}
    for present, expected in ((None, document['playback']), (edited, edited)):
        with store.connect() as conn:
            document.pop('playback', None)
            if present is not None:
                document['playback'] = present
            conn.execute("UPDATE backend_config SET document = %s WHERE name = 'replay-timing'", (Jsonb(document),))
            conn.execute("DELETE FROM schema_migrations WHERE version = '037_replay_playback.py'")
        store.initialize()
        with store.connect() as conn:
            stored = conn.execute("SELECT document FROM backend_config WHERE name = 'replay-timing'").fetchone()['document']
        assert stored['playback'] == expected
