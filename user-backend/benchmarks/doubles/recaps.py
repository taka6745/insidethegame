"""Deterministic synthetic recap archive, never an LLM narrative implementation."""
from benchmarks.doubles.recap_model import ContextBlock


def build_recaps(payload, events, cards=()):
    """Recaps from canonical events (a narrative double); tail and key events from SPADL actions and
    MA3 cards, as adapters/engine_history serves them."""
    from backend.adapters.engine_history import key_kind
    from backend.services.question_tools import compact_action
    snapshot = payload.snapshot
    end = (snapshot.clock_seconds or 0) // 60 * 60
    archive, minutes, fives = [], [], []
    earlier = None
    teams = {t['id']: t['name'] for t in payload.teams}

    def summary(start, stop):
        selected = [e for e in events if start <= e.match_time_seconds < stop]
        # Only observed categories; do not infer pressure, possession or intention.
        counts = {}
        for e in selected:
            key = (teams.get(e.team_id, 'Unassigned'), e.event_type)
            counts[key] = counts.get(key, 0) + 1
        text = '; '.join(f'{team}: {count} {kind} events' for (team, kind), count in sorted(counts.items()))
        return text or 'No recorded events in this interval.'

    def block(tier, start, stop, children=()):
        row = ContextBlock(id=f'recap:{tier}:{start}:{stop}', match_id=snapshot.match_id,
                           tier=tier, start_seconds=start, end_seconds=stop,
                           summary=summary(start, stop), created_seq=snapshot.seq,
                           child_ids=[c.id for c in children])
        for child in children:
            child.superseded_by, child.supersession_seq = row.id, snapshot.seq
        archive.append(row)
        return row

    for start in range(0, end, 60):
        minutes.append(block('minute', start, start + 60))
        if len(minutes) == 11:
            children, minutes = minutes[:5], minutes[5:]
            fives.append(block('five-minute', children[0].start_seconds, children[-1].end_seconds, children))
        if len(fives) == 4:
            children, fives = fives[:2], fives[2:]
            if earlier:
                children.insert(0, earlier)
            earlier = block('earlier', children[0].start_seconds, children[-1].end_seconds, children)
    active = ([earlier] if earlier else []) + fives + minutes
    return {'blocks': [r.model_dump() for r in active],
            'archive': [r.model_dump() for r in archive], 'coverage_end_seconds': end,
            'tail': [compact_action(a.row()) for a in payload.actions if a.match_time_seconds >= end],
            'key_events': sorted([*(compact_action(a.row()) for a in payload.actions if key_kind(a.row())), *cards],
                                 key=lambda e: (e['period'], e['match_time_seconds'])),
            'available_tiers': ['minute', 'five-minute', 'earlier'], 'complete': True, 'synthetic': True}
