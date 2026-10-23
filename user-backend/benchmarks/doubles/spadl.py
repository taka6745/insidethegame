"""Test double: SPADL rows (DAB spadlActions shape) and MA3 card rows. Hand-authored fixtures map through a simple
table (final at the event's last revision; deleted events and touches have no action); shipped recordings use
ETL's real converter (`recording_actions`)."""
import json
from pathlib import Path

LENGTH, WIDTH = 105.0, 68.0
TYPES = {'pass': 'pass', 'corner': 'corner_crossed', 'shot': 'shot', 'goal': 'shot', 'save': 'keeper_save',
         'tackle': 'tackle', 'clearance': 'clearance', 'interception': 'interception', 'foul': 'foul',
         'throw_in': 'throw_in', 'goal_kick': 'goalkick', 'take_on': 'take_on', 'keeper_claim': 'keeper_claim',
         'punch': 'keeper_punch', 'keeper_pickup': 'keeper_pick_up', 'blocked_pass': 'interception',
         'ball_touch': 'bad_touch'}
SHOT_SOURCE = {'saved': 15, 'blocked': 15, 'off_target': 13, 'post': 14}
BODY = {'head': 'head', 'right_foot': 'foot_right', 'left_foot': 'foot_left', 'foot': 'foot', 'other': 'other',
        'hand': 'other'}
CARD = {'yellow': 31, 'second_yellow': 32, 'red': 33}


def zone(x, y):
    """Team-relative zone (etl/reference/spadl.zone)."""
    band = abs(y - WIDTH / 2) <= 20.16
    if x >= LENGTH - 16.5 and band:
        return 'opp_box'
    if x <= 16.5 and band:
        return 'own_box'
    return 'defensive_third' if x < LENGTH / 3 else 'middle_third' if x < 2 * LENGTH / 3 else 'final_third'


def _latest(events):
    """event_id -> (latest revision, its seq), in first-delivery order."""
    found = {}
    for seq, event in enumerate(events, 1):
        if event.event_id not in found or event.revision > found[event.event_id][0].revision:
            found[event.event_id] = (event, seq)
    return found


def actions_from_events(events, home):
    """Canonical events (seq = index + 1) → DAB spadlActions rows in action order."""
    rows = []
    for event, final in _latest(events).values():
        kind = TYPES.get(event.event_type)
        if event.deleted or kind is None or event.team_id is None:
            continue
        first = next(i for i, e in enumerate(events, 1) if e.event_id == event.event_id)
        part = BODY.get(event.body_part)
        sx = (event.x if event.x is not None else 50.0) * LENGTH / 100
        sy = (event.y if event.y is not None else 50.0) * WIDTH / 100
        if event.event_type in ('shot', 'goal'):
            ex, ey = (95.0 if event.outcome == 'blocked' else LENGTH), WIDTH / 2
        else:
            ex, ey = min(LENGTH, sx + (event.distance_metres or 0.0)), sy
        result = ('success' if event.event_type == 'goal' else 'fail' if event.event_type in ('shot', 'foul')
                  else 'fail' if event.outcome == 'failure' else 'success')
        source = 16 if event.event_type == 'goal' else SHOT_SOURCE.get(event.outcome) if event.event_type == 'shot' else None
        mirror = event.team_id != home
        fx = (lambda v: LENGTH - v) if mirror else (lambda v: v)
        fy = (lambda v: WIDTH - v) if mirror else (lambda v: v)
        clock = event.match_time_seconds
        rows.append({'actionId': len(rows), 'periodId': event.period, 'teamId': event.team_id,
                     'playerId': event.player_id, 'typeName': kind, 'resultName': result,
                     'bodypartName': part or ('other' if kind.startswith('keeper') else 'foot'),
                     'bodypartObserved': part is not None, 'startX': fx(sx), 'startY': fy(sy), 'endX': fx(ex),
                     'endY': fy(ey), 'startZone': zone(sx, sy), 'endZone': zone(ex, ey), 'seq': first,
                     'finalSeq': final, 'sourceEventId': event.event_id, 'sourceTypeId': source,
                     'clockSeconds': clock, 'videoSeconds': event.video_seconds, 'possessionId': event.possession_id})
    # finalSeq must not decrease in actionId order (the contract); a later correction holds the rest back.
    for before, row in zip(rows, rows[1:]):
        row['finalSeq'] = max(row['finalSeq'], before['finalSeq'])
    return rows


RAW_TYPES = {'card': 17, 'goal': 16, 'period_start': 32, 'period_end': 30}


def raw_from_events(events):
    """Canonical cards, goals and period markers → DAB rawEvents rows (Opta 17, 16, 32, 30) with their eventSeq."""
    rows = []
    for event, _ in _latest(events).values():
        if event.event_type not in RAW_TYPES or event.deleted:
            continue
        seq = next(i for i, e in enumerate(events, 1) if e.event_id == event.event_id)
        quals = [{'qualifierId': CARD.get(event.outcome, 31)}] if event.event_type == 'card' else []
        payload = {'eventSeq': seq, 'eventId': seq, 'videoSeconds': event.video_seconds, 'qualifier': quals}
        rows.append({'id': seq, 'typeId': RAW_TYPES[event.event_type], 'periodId': event.period,
                     'timeMin': event.match_time_seconds // 60, 'timeSec': event.match_time_seconds % 60,
                     'contestantId': event.team_id, 'playerId': event.player_id, 'eventSeq': seq,
                     'payload': json.dumps(payload)})
    return rows


def ma3_rows(recording):
    """A shipped or archived recording's MA3 stream (`*.opta-stream.jsonl` beside it)."""
    path = Path(recording).with_name(Path(recording).name.removesuffix('.json') + '.opta-stream.jsonl')
    messages = map(json.loads, path.read_text().splitlines())
    return [m for m in messages if m.get('feed') == 'MA3']


def recording_actions(recording, home):
    """(spadlActions rows, rawEvents rows) of a shipped recording, through ETL's real converter."""
    import sys
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / 'etl'))
    from reference import spadl
    raw = ma3_rows(recording)
    rows = [{'id': m['id'], 'typeId': m['typeId'], 'periodId': m['periodId'], 'timeMin': m['timeMin'],
             'timeSec': m['timeSec'], 'contestantId': m['contestantId'], 'playerId': m.get('playerId'),
             'eventSeq': m.get('eventSeq'), 'payload': json.dumps(m)} for m in raw]
    return spadl.actions(raw, home), rows


def page(rows, after, size):
    """GraphQL-style paging over rows: (items, hasNextPage, endCursor)."""
    start = int(after or 0)
    return rows[start:start + size], start + size < len(rows), str(start + size)

