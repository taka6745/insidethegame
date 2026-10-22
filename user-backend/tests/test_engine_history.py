"""Narrative history for questions: engine contextBlocks (by tier), SPADL tails and key moments from
actions and MA3 cards, never past the snapshot."""
import asyncio
import json
from types import SimpleNamespace

import httpx

from backend.adapters.engine_history import EngineHistoryData
from backend.adapters.hls_media import HlsMedia, parse_segments
from benchmarks.doubles.config import SeededConfig

SNAPSHOT = SimpleNamespace(id='m:40', match_id='m', seq=40, period=1, clock_seconds=630)


def block(block_id, tier, start, end, period=1, superseded=None):
    return {'id': block_id, 'tier': tier, 'summary': f'summary {block_id}', 'supersededBy': superseded,
            'coversFrom': {'periodId': period, 'timeMin': start}, 'coversTo': {'periodId': period, 'timeMin': end}}


class Actions:
    def __init__(self, rows, cards=()):
        self.rows, self.card_rows = rows, list(cards)

    async def actions(self, snapshot, offset=0, limit=100, **unused):
        return {'items': self.rows[offset:offset + limit], 'has_more': offset + limit < len(self.rows)}

    async def cards(self, snapshot):
        return self.card_rows


def action(action_id, kind, seconds, period=1, result='success'):
    return {'id': action_id, 'action_type': kind, 'result': result, 'period': period, 'match_time_seconds': seconds,
            'video_seconds': float(seconds), 'team_id': 'chelsea', 'player_id': 'p', 'bodypart': 'foot',
            'start_zone': 'opp_box', 'end_zone': 'opp_box'}


def card(card_id, colour, seconds, period=1):
    return {'id': card_id, 'seq': 1, 'colour': colour, 'team_id': 'chelsea', 'player_id': 'p', 'period': period,
            'match_time_seconds': seconds, 'video_seconds': float(seconds)}


def history(blocks, rows=(), cards=()):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)['variables'])
        return httpx.Response(200, json={'data': {'contextBlocks': blocks}})
    return EngineHistoryData('http://engine/graphql', Actions(list(rows), cards), SeededConfig(),
                             transport=httpx.MockTransport(handler)), seen


def test_recaps_come_from_the_engine_by_match_id_and_never_pass_the_snapshot():
    blocks = [block('a', 'minute', 0, 0, superseded='f'), block('b', 'minute', 1, 1, superseded='f'),
              block('f', 'five-minute', 0, 4), block('k', 'minute', 9, 9), block('late', 'minute', 10, 10),
              block('p2', 'minute', 45, 45, period=2), block('x', 'unknown-tier', 0, 1)]
    data, seen = history(blocks, [action('a1', 'pass', 620)])
    page = asyncio.run(data.recaps(SNAPSHOT))
    assert [r['id'] for r in page['items']] == ['recap:f', 'recap:a', 'recap:b', 'recap:k']
    assert seen[0] == {'m': 'm'}  # The match's own history; matchIds are never shared.
    assert {r['tier'] for r in page['items']} == {'minute', 'five-minute'}
    compact = asyncio.run(data.compact(SNAPSHOT))
    assert [r['id'] for r in compact['blocks']] == ['recap:f', 'recap:k']
    assert compact['coverage_end_seconds'] == 600 and [e['id'] for e in compact['tail']] == ['a1']


def test_a_block_superseded_after_the_snapshot_is_current_at_it():
    # Minutes 5-9 compressed into a five-minute block that ends after the snapshot (10:30): that block is
    # unreachable, so its minutes stay the summary, with no trace of the later block.
    blocks = [block(f'm{i}', 'minute', i, i, superseded='later') for i in range(5, 10)] + \
             [block('later', 'five-minute', 5, 10)]
    data, _ = history(blocks)
    compact = asyncio.run(data.compact(SNAPSHOT))
    assert [r['id'] for r in compact['blocks']] == [f'recap:m{i}' for i in range(5, 10)]
    assert compact['coverage_end_seconds'] == 600
    assert all(r['superseded_by'] is None for r in asyncio.run(data.recaps(SNAPSHOT))['items'])


def test_the_engine_tier_selects_half_recaps():
    blocks = [block('h1', 'half', 0, 46), block('t', 'twenty-minute', 0, 19), block('m', 'minute', 45, 45, period=2)]
    data, _ = history(blocks)
    second_half = SimpleNamespace(**{**vars(SNAPSHOT), 'period': 2, 'clock_seconds': 2760})
    assert [r['id'] for r in asyncio.run(data.read(second_half, 'tier_recaps', tier='half'))['items']] == ['recap:h1']
    assert asyncio.run(data.read(SNAPSHOT, 'tier_recaps', tier='half'))['items'] == []


def test_key_moments_are_received_facts_ranked_by_configured_importance():
    rows = [action('a1', 'shot', 500), action('a2', 'shot', 400, result='fail'), action('a3', 'pass', 200),
            action('a4', 'bad_touch', 450, result='owngoal')]
    data, _ = history([], rows, [card('card:7', 'yellow', 100), card('card:9', 'second_yellow', 300)])
    moments = asyncio.run(data.read(SNAPSHOT, 'key_moments'))['items']
    assert {m['id']: m['rank'] for m in moments} == {'moment:a4': 1, 'moment:a1': 2, 'moment:card:9': 3, 'moment:card:7': 4}
    titles = {m['id']: m['title'] for m in moments}
    assert titles['moment:a4'].endswith('own goal') and titles['moment:card:9'].endswith('second yellow card')
    assert all(m['end_video_seconds'] <= 504 for m in moments)
    compact = asyncio.run(data.compact(SNAPSHOT))
    assert [e['id'] for e in compact['key_events']] == ['card:7', 'card:9', 'a4', 'a1']
    assert asyncio.run(data.read(SNAPSHOT, 'key_moments', period=2))['items'] == []


def test_storylines_are_as_the_snapshot_knew_them():
    at = lambda minute: {'periodId': 1, 'timeMin': minute}
    line = {'id': 'sl:m:1', 'label': 'Press', 'team': 'chelsea', 'status': 'resolved', 'outcome': 'faded',
            'openedAt': at(3), 'resolvedAt': at(30), 'salienceHistory': [{'at': at(3), 'salience': 0.4},
                                                                        {'at': at(20), 'salience': 1.5}],
            'beats': [{'at': at(3), 'headline': 'early'}, {'at': at(20), 'headline': 'late'}]}
    lines = [line, {**line, 'id': 'sl:m:2', 'status': 'dormant', 'resolvedAt': None}, {**line, 'openedAt': at(12)}]
    data = EngineHistoryData('http://engine/graphql', Actions([]), SeededConfig(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'data': {'storylines': lines}})))
    rows = asyncio.run(data.storylines(SNAPSHOT))  # 10:30 has passed minute 9's analysis only
    assert [(r['id'], r['status'], r['salience'], r['outcome'], r['beats']) for r in rows] == [
        ('sl:m:1', 'active', 0.4, None, ['early']), ('sl:m:2', 'active', 0.4, None, ['early'])]


def test_a_reopened_storyline_is_resolved_only_between_its_resolution_and_the_next_beat():
    at = lambda minute: {'periodId': 1, 'timeMin': minute}
    base = {'label': 'Press', 'team': 'chelsea', 'status': 'active', 'outcome': None, 'openedAt': at(3),
            'resolvedAt': None, 'salienceHistory': [{'at': at(3), 'salience': 0.4}]}
    lines = [{**base, 'id': 'sl:m:1', 'resolutions': [{'at': at(5), 'outcome': 'first'}],
              'beats': [{'at': at(3), 'headline': 'early'}, {'at': at(8), 'headline': 'back'}]},
             {**base, 'id': 'sl:m:2', 'resolutions': [{'at': at(9), 'outcome': 'gone'}],
              'beats': [{'at': at(3), 'headline': 'early'}, {'at': at(12), 'headline': 'back'}]}]
    data = EngineHistoryData('http://engine/graphql', Actions([]), SeededConfig(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'data': {'storylines': lines}})))
    rows = asyncio.run(data.storylines(SNAPSHOT))  # 10:30: the first reopened at 8', the second not yet
    assert [(r['id'], r['status'], r['outcome']) for r in rows] == [('sl:m:1', 'active', None),
                                                                      ('sl:m:2', 'resolved', 'gone')]


def test_no_history_before_the_first_event():
    data, seen = history([block('a', 'minute', 0, 0)])
    empty = SimpleNamespace(**{**vars(SNAPSHOT), 'clock_seconds': None, 'period': None})
    assert asyncio.run(data.recaps(empty))['items'] == [] and seen == []


def test_replay_edge_is_the_feeds_published_playlist_over_http():
    playlists = {'/hls/m/live.m3u8': '#EXTM3U\n#EXTINF:6.0,\nseg0.ts\n#EXTINF:4.5,\nseg1.ts\n'}

    def handler(request):
        body = playlists.get(request.url.path)
        return httpx.Response(200, text=body) if body else httpx.Response(404)
    media = HlsMedia('http://feed:8000/hls', transport=httpx.MockTransport(handler))
    assert asyncio.run(media.published_edge('m')) == 10.5
    assert asyncio.run(media.published_edge('purged')) == 0.0  # 404: nothing played or purged.
    assert media.stream_url('m') == '/media/hls/m/live.m3u8'
    assert parse_segments(playlists['/hls/m/live.m3u8']) == [('seg0.ts', 0.0, 6.0), ('seg1.ts', 6.0, 4.5)]
