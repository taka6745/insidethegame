"""Broadcast clock: periods restart at nominal times and run into stoppage.

Clock seconds alone are ambiguous (45:30 exists in both halves), so every
comparison uses (period, seconds) or delivery order.
"""
PERIOD_START_SECONDS = {1: 0, 2: 2700, 3: 5400, 4: 6300, 5: 7200}
PERIOD_END_MINUTE = {1: 45, 2: 90, 3: 105, 4: 120}


def position(event):
    return (event.get('period') or 1, event['match_time_seconds'])


def minute_label(period, minute):
    """Broadcast minute (1-based, timeMin + 1): period 1 minute 47 is 45+2'."""
    end = PERIOD_END_MINUTE.get(period)
    return f"{end}+{minute - end}'" if end is not None and minute > end else f"{minute}'"


def minute_id(period, minute):
    return f'p{period}-m{minute}'
