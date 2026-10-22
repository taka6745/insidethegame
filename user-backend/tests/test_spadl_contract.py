"""SPADL contract in the backend: the action model, the generated reference, the profile and lookup_spadl."""
import json
from pathlib import Path

import pytest

from backend.adapters.feed_reference import FeedReference
from backend.models.actions import SpadlAction
from backend.services.spadl_lookup import MAX_CHARS, lookup

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(__file__).resolve().parents[1] / 'backend' / 'contracts' / 'spadl-reference.json'


def row(**changes):
    """One DAB spadlActions item (SPADL standard frame: the home team attacks towards x = 105)."""
    return {'actionId': 3, 'periodId': 2, 'teamId': 'away', 'playerId': 'a-9', 'typeName': 'shot',
            'resultName': 'fail', 'bodypartName': 'head', 'bodypartObserved': True, 'startX': 10.0, 'startY': 30.0,
            'endX': 0.0, 'endY': 34.0, 'startZone': 'opp_box', 'endZone': 'opp_box', 'seq': 40, 'finalSeq': 40,
            'sourceEventId': 'e40', 'sourceTypeId': 15, 'clockSeconds': 2950.5, 'videoSeconds': 3001.0,
            'possessionId': 7} | changes


def test_from_row_unmirrors_away_actions_and_floors_the_clock():
    away = SpadlAction.from_row(row(), 'm', 'home')
    assert (away.start_x, away.start_y, away.end_x, away.end_y) == (95.0, 38.0, 105.0, 34.0)
    assert away.match_time_seconds == 2950 and away.period == 2 and away.id == 'a3'
    home = SpadlAction.from_row(row(teamId='home'), 'm', 'home')
    assert (home.start_x, home.end_x) == (10.0, 0.0)  # Already team-relative.
    assert round(away.distance_metres, 3) == round(((105 - 95) ** 2 + (34 - 38) ** 2) ** .5, 3)


@pytest.mark.parametrize('changes, outcome', [
    ({}, 'saved'),                                           # Opta 15 reaching the goal line: on target.
    ({'endX': 8.0}, 'blocked'),                              # Opta 15 stopped before the line.
    ({'sourceTypeId': 14}, 'post'),
    ({'sourceTypeId': 13}, 'off_target'),
    ({'resultName': 'success', 'sourceTypeId': 16}, 'goal'),
    ({'typeName': 'pass', 'resultName': 'success'}, None),   # Not a shot type.
])
def test_shot_outcome_follows_the_catalogue_on_target_rules(changes, outcome):
    assert SpadlAction.from_row(row(**changes), 'm', 'home').shot_outcome == outcome


@pytest.mark.parametrize('changes, kind', [
    ({}, 'save'), ({'fromShotOffTarget': True}, 'wide_touch'), ({'defensiveBlock': True}, 'block'),
    ({'typeName': 'shot', 'defensiveBlock': True}, None),
])
def test_save_kind_splits_keeper_saves_as_etl_shots_saved(changes, kind):
    action = SpadlAction.from_row(row(**{'typeName': 'keeper_save', 'resultName': 'success', 'sourceTypeId': 10,
                                         **changes}), 'm', 'home')
    assert action.save_kind == kind and action.row()['save_kind'] == kind
    from backend.models.rules import Predicate
    assert Predicate(field='save_kind', op='eq', value='save').matches(action) == (kind == 'save')


def test_generated_reference_is_fresh():
    if not (ROOT / 'etl' / 'reference' / 'spadl.py').exists():
        pytest.skip('The ETL contract is not beside this checkout')
    import importlib.util  # By path: etl/ also has a `devtools` package on sys.path in this run.
    spec = importlib.util.spec_from_file_location('backend_spadl_reference',
                                                  Path(__file__).parents[1] / 'devtools' / 'spadl_reference.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert json.loads(REFERENCE.read_text()) == json.loads(json.dumps(module.build()))


def test_profile_must_match_the_action_model():
    profile = FeedReference.load()
    assert profile.describe()['contract_id'] == 'spadl-v1'
    broken = profile.model_copy(update={'events': {k: v for k, v in profile.events.items() if k != 'dribble'}})
    with pytest.raises(ValueError, match='events'):
        broken.describe()


STATS = [{'id': 'all:crosses', 'label': 'Both teams crosses', 'action_types': ['cross', 'corner_crossed', 'freekick_crossed'],
          'definition': 'SPADL cross, corner_crossed and freekick_crossed actions.', 'available': True},
         {'id': 'chelsea:crosses', 'label': 'Chelsea crosses', 'action_types': ['cross'], 'definition': '', 'available': True},
         {'id': 'all:box_entries', 'label': 'Both teams box entries', 'action_types': ['pass', 'dribble'],
          'definition': 'Successful SPADL passes and dribbles into the opponent penalty area.', 'available': True}]


def test_lookup_answers_types_zones_stats_and_unknown_terms_within_the_cap():
    cross = lookup('Cross', STATS)
    assert cross['kind'] == 'type' and cross['goal_example'] == {'action_types': ['cross']}
    assert any('Opta 1' in source for source in cross['opta_source'])
    assert any(text.startswith('crosses:') for text in cross['catalogue_stats'])
    zone = lookup('opp box', STATS)
    assert zone['kind'] == 'zone' and zone['goal_example']['end_zones'] == ['opp_box']
    assert any(text.startswith('box_entries:') for text in zone['catalogue_stats'])
    stat = lookup('chelsea:crosses', STATS)
    assert stat['kind'] == 'catalogue_stat' and stat['ids'] == ['all:crosses', 'chelsea:crosses']
    unknown = lookup('aerial duel', STATS)
    assert unknown['unknown'] and 'cross' in unknown['known']['types']
    for term in ('pass', 'fail', 'head', 'final_third', 'crosses', 'start_x', 'interception'):
        assert len(json.dumps(lookup(term, STATS * 20), ensure_ascii=False)) <= MAX_CHARS
