"""Demo standard projections, calculated once at ingestion, never by viewers."""
from collections import Counter


def observed(deliveries):
    latest, revisions, first_seen = {}, {}, {}
    for index, event in enumerate(deliveries):
        first_seen.setdefault(event.event_id, index)
        key = (event.event_id,event.revision)
        if key in revisions and revisions[key] != event:
            raise ValueError('Conflicting event revision')
        revisions[key] = event
        previous = latest.get(event.event_id)
        if previous is not None and previous.revision == event.revision and previous != event:
            raise ValueError('Conflicting event revision')
        if previous is None or event.revision > previous.revision:
            latest[event.event_id] = event
    # Stoppage time repeats clock values across periods; delivery order breaks same-second ties.
    return sorted((e for e in latest.values() if not e.deleted),
                  key=lambda e: (e.period, e.match_time_seconds, first_seen[e.event_id]))


def project(payload, possession=None, capabilities=None):
    events = observed(payload.events)
    possession = Counter(possession or {})
    total_possession = sum(possession.values())
    stats = []
    capabilities = capabilities or {}
    supported = set(capabilities.get("supported_event_types", ("pass","shot","goal","corner","card","save","tackle","interception","foul")))
    shot_types = ("shot",) if capabilities.get("shots_include_scoring_attempts") else ("shot","goal")
    for team in [None, *payload.teams]:
        team_id = team['id'] if team else None
        rows = [e for e in events if team_id is None or e.team_id == team_id]
        counts = Counter(e.event_type for e in rows)
        kinds = [('goals', ('goal',)), ('shots', shot_types), ('passes', ('pass',)),
                 ('corners', ('corner',)), ('cards', ('card',)),
                 ('tackles', ('tackle',)), ('interceptions', ('interception',)), ('fouls', ('foul',)),
                 ('fouls_won', ('foul_won',)), ('offsides', ('offside',)),
                 ('throw_ins', ('throw_in',)), ('free_kicks', ('free_kick',)),
                 ('goal_kicks', ('goal_kick',)), ('kick_offs', ('kick_off',)),
                 ('penalties', ('penalty',)), ('keeper_claims', ('keeper_claim',)),
                 ('clearances', ('clearance',)), ('take_ons', ('take_on',)),
                 ('ball_recoveries', ('ball_recovery',))]
        def append(kind, value, definition, types=(), available=True):
            if not available:
                value = None
            stats.append({'id': f'{team_id or "all"}:{kind}',
                'label': f'{team["name"] if team else "Both teams"} {kind.replace("_", " ")}',
                'value': value, 'available': available, 'team_id': team_id,
                'unit': '%' if kind in ('possession', 'pass_accuracy') else '',
                'definition': definition, 'event_types': list(types), 'complete': True})
        for kind, types in kinds:
            definition = f'Observed {", ".join(types)} events; latest non-deleted revisions.'
            if types[0] in ('throw_in', 'free_kick', 'goal_kick', 'kick_off', 'penalty') or (
                kind == 'corners' and capabilities.get('restart_events') == 'taken'
            ):
                definition = 'Restarts actually taken, not merely awarded; latest non-deleted revisions.'
            elif kind == 'fouls':
                definition = 'Whistled fouls committed; excludes offsides and companion foul-won records.'
            append(kind, sum(counts[t] for t in types) if set(types) <= supported else None,
                   definition, types, set(types) <= supported)
        body_types = set(capabilities.get('body_part_event_types', ()))
        for kind, types in [('headed_passes', ('pass',)), ('headed_shots', shot_types),
                            ('headed_contacts', ('touch',))]:
            available = set(types) <= supported and (
                capabilities.get('body_parts', False) or set(types) <= body_types)
            append(kind, sum(e.event_type in types and e.body_part == 'head' for e in rows),
                   f'Head contacts among {", ".join(types)} records; requires complete body-part coverage for each category.',
                   types, available)
        # Opta saves: goalkeeper stops of on-target attempts. Outfield blocks and tips of
        # off-target attempts are save records too, but not saves.
        keeper_saves = sum(e.event_type == 'save' and not (e.qualifiers or {}).get('defensiveBlock')
                           and not (e.qualifiers or {}).get('fromShotOffTarget') for e in rows)
        append('saves', keeper_saves, 'Goalkeeper saves of on-target attempts; excludes outfield blocks.',
               ('save',), 'save' in supported)
        # Goals are distinct from non-goal shot events in this adapter contract.
        on_target = counts['goal'] + sum(e.event_type == 'shot' and e.outcome in ('saved','on_target') for e in rows)
        append('shots_on_target', on_target, 'Goals plus non-goal shots explicitly recorded saved/on_target.', ('shot','goal'), {'shot', 'goal'} <= supported and capabilities.get('shot_outcomes', True))
        shot_outcomes = 'shot' in supported and capabilities.get('shot_outcomes', True)
        append('blocked_shots', sum(e.event_type == 'shot' and e.outcome == 'blocked' for e in rows),
               "Team's non-goal shots recorded blocked.", ('shot',), shot_outcomes)
        for kind, kind_type in [('aerials_won', 'aerial'), ('successful_take_ons', 'take_on')]:
            append(kind, sum(e.event_type == kind_type and e.outcome == 'success' for e in rows),
                   f'{kind_type} records with success outcome; latest non-deleted revisions.',
                   (kind_type,), kind_type in supported)
        passes = [e for e in rows if e.event_type == 'pass']
        known = [e for e in passes if e.outcome in ('success','failure')]
        append('pass_accuracy', round(100 * sum(e.outcome == 'success' for e in known) / len(known), 1) if known else None,
               'Successful resolved passes / all resolved passes (%); unknown outcomes excluded.', ('pass',), bool(known))
        append('possession', round(100 * (possession[team_id] if team_id else total_possession) / total_possession, 1) if total_possession else None,
               'Share of measured native simulation ball-ownership seconds; unowned ball excluded.', (), bool(total_possession))
    return stats
