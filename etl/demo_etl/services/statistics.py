"""Demo standard projections, calculated once at ingestion, never by viewers."""
from collections import Counter


def observed(deliveries):
    latest, revisions = {}, {}
    for event in deliveries:
        key = (event.event_id,event.revision)
        if key in revisions and revisions[key] != event:
            raise ValueError('Conflicting event revision')
        revisions[key] = event
        previous = latest.get(event.event_id)
        if previous is not None and previous.revision == event.revision and previous != event:
            raise ValueError('Conflicting event revision')
        if previous is None or event.revision > previous.revision:
            latest[event.event_id] = event
    return sorted((e for e in latest.values() if not e.deleted), key=lambda e: (e.period, e.match_time_seconds, e.event_id))


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
                 ('corners', ('corner',)), ('cards', ('card',)), ('saves', ('save',)),
                 ('tackles', ('tackle',)), ('interceptions', ('interception',)), ('fouls', ('foul',)),
                 ('fouls_won', ('foul_won',)), ('offsides', ('offside',)),
                 ('throw_ins', ('throw_in',)), ('free_kicks', ('free_kick',)),
                 ('goal_kicks', ('goal_kick',)), ('kick_offs', ('kick_off',)),
                 ('penalties', ('penalty',)), ('keeper_claims', ('keeper_claim',))]
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
        # Goals are distinct from non-goal shot events in this adapter contract.
        on_target = counts['goal'] + sum(e.event_type == 'shot' and e.outcome in ('saved','on_target') for e in rows)
        append('shots_on_target', on_target, 'Goals plus non-goal shots explicitly recorded saved/on_target.', ('shot','goal'), {'shot', 'goal'} <= supported and capabilities.get('shot_outcomes', True))
        passes = [e for e in rows if e.event_type == 'pass']
        known = [e for e in passes if e.outcome in ('success','failure')]
        append('pass_accuracy', round(100 * sum(e.outcome == 'success' for e in known) / len(known), 1) if known else None,
               'Successful resolved passes / all resolved passes (%); unknown outcomes excluded.', ('pass',), bool(known))
        append('possession', round(100 * (possession[team_id] if team_id else total_possession) / total_possession, 1) if total_possession else None,
               'Share of measured native simulation ball-ownership seconds; unowned ball excluded.', (), bool(total_possession))
    return stats
