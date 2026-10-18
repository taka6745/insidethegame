"""Native v2 restarts and referee decisions remain separate counting dimensions."""
import pytest

from demo_etl.adapters.recording import adapt_event
from demo_etl.services.statistics import project
from test_etl import payload, values


def native(kind, sequence=1, **changes):
    return {'eventId': f'native-{sequence}', 'matchId': 'match', 'sequence': sequence,
            'typeName': kind, 'teamId': 'chelsea', 'playerId': 'palmer',
            'periodId': 1, 'timeMin': 20, 'timeSec': 0, 'qualifiers': [], **changes}


@pytest.mark.parametrize('kind', [
    'throw_in', 'free_kick', 'goal_kick', 'kick_off', 'penalty', 'offside',
    'foul_won', 'keeper_claim', 'period_start', 'period_end',
])
def test_adapter_accepts_native_categories_and_ignores_uncanonical_qualifiers(kind):
    event = adapt_event(native(kind, qualifiers=[{'type': 'relatedEventId', 'value': 'native-0'}]))
    assert event.event_type == kind
    assert 'relatedEventId' not in event.model_dump()


def test_standard_projections_do_not_double_count_restart_action_or_foul_participants():
    kinds = ['corner', 'pass', 'foul', 'foul_won', 'offside', 'free_kick', 'pass',
             'penalty', 'goal', 'throw_in', 'pass', 'goal_kick', 'pass', 'kick_off',
             'keeper_claim', 'card', 'period_start', 'period_end']
    rows = [adapt_event(native(kind, index + 1)) for index, kind in enumerate(kinds)]
    # Duplicate broker delivery must not duplicate any standard statistic.
    rows.append(rows[0])
    stats = values(project(payload(rows), capabilities={
        'supported_event_types': sorted(set(kinds) | {'shot'}),
        'restart_events': 'taken', 'shot_outcomes': False,
    }))
    assert stats['fouls']['value'] == stats['fouls_won']['value'] == 1
    assert stats['corners']['value'] == stats['offsides']['value'] == 1
    assert stats['passes']['value'] == 4
    assert stats['shots']['value'] == stats['goals']['value'] == 1
    for kind in ('throw_ins', 'free_kicks', 'goal_kicks', 'kick_offs', 'penalties', 'keeper_claims'):
        assert stats[kind]['value'] == 1
    assert 'actually taken' in stats['corners']['definition']
    assert stats['saves']['value'] is None
    assert stats['shots_on_target']['value'] is None


def test_unsupported_channels_remain_unavailable_even_when_rows_are_empty():
    stats = values(project(payload([]), capabilities={'supported_event_types': ['foul', 'offside']}))
    assert stats['fouls']['value'] == stats['offsides']['value'] == 0
    for kind in ('penalties', 'throw_ins', 'keeper_claims', 'shots_on_target'):
        assert stats[kind]['available'] is False
        assert stats[kind]['value'] is None


def test_unknown_native_categories_are_rejected():
    with pytest.raises(ValueError):
        adapt_event(native('var_review'))


def test_card_outcomes_and_headed_action_survive_translation():
    card = adapt_event(native('card', outcome='second_yellow'))
    header = adapt_event(native('pass', qualifiers=[{'type': 'bodyPart', 'value': 'head'},
                                                  {'type': 'intent', 'value': 'short_pass'}]))
    assert card.outcome == 'second_yellow'
    assert header.body_part == 'head' and header.event_type == 'pass'


@pytest.mark.parametrize('coverage', [
    {'body_parts': True},
    {'body_parts': False, 'body_part_event_types': ['pass', 'shot', 'goal', 'touch']},
])
def test_headed_standard_stats_require_covered_categories_and_count_actions_once(coverage):
    rows = [adapt_event(native(kind, index, qualifiers=[{'type': 'bodyPart', 'value': part}]))
            for index, (kind, part) in enumerate([
                ('pass', 'head'), ('shot', 'head'), ('goal', 'head'),
                ('touch', 'head'), ('pass', 'left_foot'), ('shot', 'right_foot')], 1)]
    rows.append(rows[0])
    stats = values(project(payload(rows), capabilities={
        'supported_event_types': ['pass', 'shot', 'goal', 'touch'], **coverage,
    }))
    assert stats['headed_passes']['value'] == 1
    assert stats['headed_shots']['value'] == 2
    assert stats['headed_contacts']['value'] == 1
    assert stats['headed_shots']['event_types'] == ['shot', 'goal']


def test_partial_body_coverage_does_not_present_known_headers_as_complete_totals():
    rows = [adapt_event(native('pass', qualifiers=[{'type': 'bodyPart', 'value': 'head'}])),
            adapt_event(native('goal', 2)),
            adapt_event(native('touch', 3, qualifiers=[{'type': 'bodyPart', 'value': 'head'}]))]
    stats = values(project(payload(rows), capabilities={
        'supported_event_types': ['pass', 'shot', 'goal', 'touch'], 'body_parts': False,
        'body_part_event_types': ['pass', 'shot'],
    }))
    assert stats['headed_passes']['value'] == 1
    for kind in ('headed_shots', 'headed_contacts'):
        assert stats[kind]['available'] is False
        assert stats[kind]['value'] is None


def test_global_body_coverage_does_not_enable_unsupported_event_categories():
    stats = values(project(payload([]), capabilities={'supported_event_types': ['pass'], 'body_parts': True}))
    assert stats['headed_passes']['value'] == 0
    assert stats['headed_shots']['value'] is None
    assert stats['headed_contacts']['value'] is None


def test_goal_inclusive_shot_channel_does_not_double_count_headed_goals():
    rows = [adapt_event(native(kind, index, qualifiers=[{'type': 'bodyPart', 'value': 'head'}]))
            for index, kind in enumerate(('shot', 'goal'), 1)]
    stats = values(project(payload(rows), capabilities={
        'supported_event_types': ['shot', 'goal'], 'body_part_event_types': ['shot'],
        'shots_include_scoring_attempts': True,
    }))
    assert stats['headed_shots']['value'] == 1
    assert stats['headed_shots']['event_types'] == ['shot']
