"""SPADL cut-over: saved rules and tracked cards follow (020), prompts gain the glossary (021), and custom
values read SPADL actions only up to the snapshot and ETL's SPADL watermark."""
import uuid

from psycopg import sql
from psycopg.types.json import Jsonb

from backend.models.rules import Rule
from backend.services.product import MatchProjection
from backend.store import MIGRATIONS, migrate
from benchmarks.doubles.config import seeded
from harness import MATCH, Running

SEEDS = MIGRATIONS / 'prompts'
OLD = lambda *predicates: {'match_id': 'm-1', 'operation': 'count', 'predicates': list(predicates)}
P = lambda field, value, op='eq': {'field': field, 'op': op, 'value': value}


def before_spadl(conn, store):
    """A schema at migration 019, as a deployment before the SPADL cut-over left it."""
    conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(store.schema)))
    conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(store.schema)))
    migrate(conn, [p for p in sorted(MIGRATIONS.glob('*.sql')) if p.name < '020'])


def migrate_until(store, before):
    """Apply the migrations named before `before` (as Store.initialize would, without the later ones)."""
    with store.connect() as conn:
        conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(store.schema)))
        migrate(conn, sorted([p for p in [*MIGRATIONS.glob('*.sql'), *MIGRATIONS.glob('[0-9]*.py')]
                              if p.name < before], key=lambda p: p.name))


def test_saved_rules_and_tracked_offers_move_to_spadl(store):
    rules = {'calc_pass': OLD(P('event_type', 'pass'), P('team_id', 'riverton')),
             'calc_shots': OLD(P('event_type', ['shot', 'goal'], 'in'), P('body_part', 'head')),
             'calc_touch': OLD(P('event_type', 'touch'), P('player_id', 'ashworth')),
             'calc_share': {'match_id': 'm-1', 'operation': 'percentage', 'inputs': [
                 OLD(P('event_type', 'pass'), P('outcome', 'success')),
                 OLD(P('event_type', 'pass'), P('outcome', ['success', 'failure'], 'in'))]}}
    conversation = uuid.uuid4()
    with store.connect() as conn:
        before_spadl(conn, store)
        conn.execute("INSERT INTO received_matches (match_id, fixture, sent_at) VALUES ('m-1', 'riverton-forgeham', now())")
        conn.execute("INSERT INTO question_conversations (id, profile_id, match_id) VALUES (%s, 'p', 'm-1')", (conversation,))
        turn = conn.execute("INSERT INTO question_turns (conversation_id, request_id, prompt, status) "
                            "VALUES (%s, %s, 'q', 'complete') RETURNING id", (conversation, uuid.uuid4())).fetchone()['id']
        for old, rule in rules.items():
            conn.execute('INSERT INTO match_calculations VALUES (%s, %s, %s, %s, %s)',
                         ('m-1', old, old, Jsonb(rule), Jsonb({'calculation_id': old, 'value': 3, 'version': 4})))
            conn.execute('INSERT INTO question_offers VALUES (%s, %s, %s, %s, %s)',
                         (uuid.uuid4(), conversation, turn, Jsonb({'label': old, 'rule': rule, 'goal': {}}), old))
        untracked = uuid.uuid4()
        conn.execute('INSERT INTO question_offers VALUES (%s, %s, %s, %s, NULL)',
                     (untracked, conversation, turn, Jsonb({'label': 'old', 'rule': rules['calc_pass']})))
    store.initialize()
    with store.connect() as conn:
        mapped = {r['old_id']: r for r in conn.execute('SELECT * FROM calculation_id_map')}
        saved = {r['calculation_id']: r for r in conn.execute('SELECT * FROM match_calculations')}
        offers = {r['document']['label']: r for r in conn.execute('SELECT * FROM question_offers')}
        vocabulary = {(r['old_field'], r['old_value']): r for r in conn.execute('SELECT * FROM rule_vocabulary_map')}
    expected = {
        'calc_pass': Rule.model_validate(OLD(P('action_type', ['pass', 'cross', 'throw_in', 'freekick_crossed',
            'freekick_short', 'corner_crossed', 'corner_short', 'goalkick'], 'in'), P('team_id', 'riverton'))),
        'calc_shots': Rule.model_validate(OLD(P('action_type', ['shot', 'shot_freekick', 'shot_penalty'], 'in'),
                                              P('bodypart', ['head'], 'in')))}
    for old, rule in expected.items():
        new = mapped[old]['new_id']
        assert new == rule.calculation_id == Rule.model_validate(saved[new]['rule']).calculation_id
        assert saved[new]['result'] == {'calculation_id': new, 'value': 0.0, 'version': 4}
        assert offers[old]['calculation_id'] == new == Rule.model_validate(offers[old]['document']['rule']).calculation_id
    share = Rule.model_validate(saved[mapped['calc_share']['new_id']]['rule'])
    assert share.composite and share.inputs[0].predicates[-1].field == 'result'
    assert mapped['calc_touch']['new_id'] is None and 'touch' in mapped['calc_touch']['reason']
    assert 'calc_touch' not in saved and offers['calc_touch']['document']['unsupported'] == mapped['calc_touch']['reason']
    assert offers['old']['document']['unsupported']  # Never tracked: its old rule cannot be tracked any more.
    assert vocabulary[('event_type', 'touch')]['supported'] is False
    assert vocabulary[('event_type', 'corner')]['spadl'] == {'action_type': ['corner_crossed', 'corner_short']}

    # The unsupported tracked card stays visible, unavailable, with its reason.
    projection = object.__new__(MatchProjection)
    projection.presentation, projection.buckets = seeded('presentation'), []
    projection.shared = {'type': 'snapshot', 'version': 1, 'projection_epoch': 'e', 'synthetic': True, 'mode': 'fixture',
                         'snapshot_id': 'm-1:1', 'events': [], 'narratives': [], 'stats': [], 'calculations': {},
                         'match': {'teams': [{'id': 'riverton'}, {'id': 'forgeham'}]}}
    viewer = {'profile': {'team': 'riverton'}, 'audience': None,
              'offers': [{**offers['calc_touch']['document'], 'calculation_id': 'calc_touch'}]}
    [card] = projection.compose(viewer)['cards']
    assert card['available'] is False and card['unavailable_reason'] == mapped['calc_touch']['reason']


def test_spadl_prompts_become_active_unless_edited(store):
    author = (SEEDS / 'narrative-author.v4.txt').read_text(encoding='utf-8')  # 021's author; 023 moves on to v5
    summary = (SEEDS / 'minute-summary.txt').read_text(encoding='utf-8')
    old = lambda text: text.split('Event lines follow SPADL')[0] + text[text.index('{'):]  # same placeholders
    from backend.models.prompts import placeholders
    with store.connect() as conn:
        before_spadl(conn, store)
        for role, text in (('narrative-author', author), ('minute-summary', summary)):
            conn.execute("INSERT INTO narrative_prompts VALUES (%s, 1, %s, %s, 'seed', now())",
                         (role, old(text), placeholders(text)))
            conn.execute('INSERT INTO narrative_prompt_active VALUES (%s, 1, 1)', (role,))
        conn.execute("INSERT INTO narrative_prompts VALUES ('minute-summary', 2, %s, %s, 'dev', now())",
                     (old(summary) + '\nBe brief.', placeholders(summary)))
        conn.execute("UPDATE narrative_prompt_active SET version=2, revision=2 WHERE role='minute-summary'")
    migrate_until(store, '023')
    with store.connect() as conn:
        active = {r['role']: r for r in conn.execute('SELECT a.role, a.version, p.template FROM narrative_prompt_active a '
                                                     'JOIN narrative_prompts p USING (role, version)')}
        versions = {(r['role'], r['version']): r['template'] for r in conn.execute('SELECT * FROM narrative_prompts')}
    assert active['narrative-author']['version'] == 2 and active['narrative-author']['template'] == author
    assert '→' in author and 'SPADL' in author
    assert active['minute-summary']['version'] == 2 and active['minute-summary']['template'].endswith('Be brief.')
    assert versions[('minute-summary', 3)] == summary  # Offered as a version, not forced over the edit.
    migrate_until(store, '023')  # Applied once.
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM narrative_prompts').fetchone()['n'] == 5


def test_storyline_prompts_add_the_analyst_and_force_author_v5_over_an_edit(store):
    from backend.models.prompts import placeholders
    v4 = (SEEDS / 'narrative-author.v4.txt').read_text(encoding='utf-8')
    v5, analyst = ((SEEDS / name).read_text(encoding='utf-8') for name in ('narrative-author.v5.txt',
                                                                           'match-analyst.v1.txt'))
    with store.connect() as conn:
        before_spadl(conn, store)
        conn.execute("INSERT INTO narrative_prompts VALUES ('narrative-author', 1, %s, %s, 'seed', now())",
                     (v4, placeholders(v4)))
        conn.execute("INSERT INTO narrative_prompts VALUES ('narrative-author', 2, %s, %s, 'dev', now())",
                     (v4 + '\nBe brief.', placeholders(v4)))
        conn.execute("INSERT INTO narrative_prompt_active VALUES ('narrative-author', 2, 4)")
    migrate_until(store, '024')
    with store.connect() as conn:
        active = {r['role']: r for r in conn.execute('SELECT a.role, a.version, a.revision, p.template, p.source '
                                                     'FROM narrative_prompt_active a JOIN narrative_prompts p '
                                                     'USING (role, version)')}
        edited = conn.execute("SELECT template FROM narrative_prompts WHERE role='narrative-author' AND version=2")
        assert edited.fetchone()['template'].endswith('Be brief.')  # kept as a version to redo on top of v5
    assert (active['narrative-author']['version'], active['narrative-author']['template']) == (3, v5)
    assert {'{storylines}', '{match_trends}'} <= set('{' + p + '}' for p in placeholders(v5))
    assert (active['match-analyst']['version'], active['match-analyst']['template']) == (1, analyst)
    assert active['narrative-author']['revision'] == 6 and active['match-analyst']['revision'] == 5
    migrate_until(store, '024')  # applied once
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM narrative_prompts').fetchone()['n'] == 4


def test_storyline_prompts_keep_an_edit_of_v5_and_skip_a_fresh_store(store):
    from backend.models.prompts import placeholders
    v5 = (SEEDS / 'narrative-author.v5.txt').read_text(encoding='utf-8')
    with store.connect() as conn:
        before_spadl(conn, store)
    migrate_until(store, '024')  # fresh: nothing to do here; startup seeds every role
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM narrative_prompt_active').fetchone()['n'] == 0
        conn.execute('DELETE FROM schema_migrations WHERE version = %s', ('023_storyline_prompts.py',))
        conn.execute("INSERT INTO narrative_prompts VALUES ('narrative-author', 1, %s, %s, 'dev', now())",
                     (v5 + '\nShorter.', placeholders(v5)))
        conn.execute("INSERT INTO narrative_prompt_active VALUES ('narrative-author', 1, 1)")
    migrate_until(store, '024')
    with store.connect() as conn:
        author = conn.execute("SELECT version FROM narrative_prompt_active WHERE role='narrative-author'").fetchone()
        assert author['version'] == 1  # already on v5's placeholders: the edit stays


def test_grounded_prompts_replace_unedited_seeds_and_keep_edits(store):
    from backend.models.prompts import placeholders
    v1, v5 = ((SEEDS / name).read_text(encoding='utf-8') for name in ('match-analyst.v1.txt', 'narrative-author.v5.txt'))
    v2, v6 = ((SEEDS / name).read_text(encoding='utf-8') for name in ('match-analyst.v2.txt', 'narrative-author.v6.txt'))
    assert placeholders(v2) == placeholders(v1) and placeholders(v6) == placeholders(v5)
    with store.connect() as conn:
        before_spadl(conn, store)
    migrate_until(store, '025')
    with store.connect() as conn:
        conn.execute("INSERT INTO narrative_prompts VALUES ('match-analyst', 1, %s, %s, 'seed', now())",
                     (v1, placeholders(v1)))
        conn.execute("INSERT INTO narrative_prompts VALUES ('narrative-author', 1, %s, %s, 'dev', now())",
                     (v5 + '\nShorter.', placeholders(v5)))
        conn.execute("INSERT INTO narrative_prompt_active VALUES ('match-analyst', 1, 1), ('narrative-author', 1, 2)")
    migrate_until(store, '026')
    with store.connect() as conn:
        active = {r['role']: r for r in conn.execute('SELECT a.role, a.version, p.template FROM narrative_prompt_active '
                                                     'a JOIN narrative_prompts p USING (role, version)')}
        added = conn.execute("SELECT template FROM narrative_prompts WHERE role='narrative-author' AND version=2")
        assert added.fetchone()['template'] == v6  # kept as a version for the edit to move onto
    assert (active['match-analyst']['version'], active['match-analyst']['template']) == (2, v2)
    assert active['narrative-author']['version'] == 1  # the /dev/ edit stays active


def test_custom_values_follow_the_snapshot_and_never_pass_the_spadl_watermark(store):
    with Running(store) as run:
        run.send(20)
        rule = Rule.model_validate({'match_id': MATCH, 'operation': 'count',
                                    'predicates': [{'field': 'action_type', 'op': 'in', 'value': ['shot']}]})
        assert run.client.post(f'/lab/matches/{MATCH}/calculations', json={'rule': rule.model_dump(mode='json')}).status_code == 201
        match, actions = run.match(), run.upstream.matches[MATCH].actions()
        shot = lambda seq: sum(a['typeName'] == 'shot' and a['finalSeq'] <= seq for a in actions)
        assert shot(3) < shot(20)
        for seq in (1, 3, 9, 20):
            assert match.value_at(rule.calculation_id, seq) == shot(seq)
        # ETL's SPADL post-processor trails: seq 30 is committed, spadlSeq only 26.
        run.upstream.spadl_lag = 4
        run.send(10)
        payload = run.client.portal.call(run.app.state.questions.match_data.capture, match)
        assert payload.snapshot.seq == 26 and match.actions_seq == 26
        assert all(a.final_seq <= 26 for a in payload.actions) and payload.actions
        assert match.calculations()[rule.calculation_id]['value'] == shot(26)
        assert run.client.portal.call(run.app.state.questions.match_data.capture, match, 29).snapshot.seq == 26



def test_replay_timing_keys_move_to_spadl_and_keep_edited_seconds(store):
    """Migration 022: canonical timing keys become SPADL types; an edited value survives."""
    from psycopg.types.json import Jsonb
    from backend.models.config import Replay
    from backend.store import MIGRATIONS, migrate
    with store.connect() as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(store.schema)))
        conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(store.schema)))
        migrate(conn, [p for p in sorted([*MIGRATIONS.glob('*.sql'), *MIGRATIONS.glob('[0-9]*.py')],
                                         key=lambda p: p.name) if p.name < '022'])
        document = conn.execute("SELECT document FROM backend_config WHERE name='replay-timing'").fetchone()['document']
        document['timing']['corner'] = [2.0, 7.0]
        conn.execute("UPDATE backend_config SET document=%s WHERE name='replay-timing'", (Jsonb(document),))
    store.initialize()
    with store.connect() as conn:
        timing = Replay.model_validate(conn.execute(
            "SELECT document FROM backend_config WHERE name='replay-timing'").fetchone()['document']).timing
    assert timing['corner_crossed'] == timing['corner_short'] == (2.0, 7.0)
    assert {'keeper_save', 'shot_penalty', 'freekick_short', 'goal', 'card'} <= set(timing)
    assert not {'save', 'corner', 'free_kick', 'offside', 'foul_won', 'corner_awarded'} & set(timing)
