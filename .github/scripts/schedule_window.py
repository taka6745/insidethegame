#!/usr/bin/env python3
"""The scheduled report runs only through 28 October 2026 in Brisbane."""
from datetime import date, datetime
import os
from zoneinfo import ZoneInfo

START = date(2026, 10, 13)
END = date(2026, 10, 28)


def active(event, now):
    return event != 'schedule' or START <= now.astimezone(ZoneInfo('Australia/Brisbane')).date() <= END


if __name__ == '__main__':
    value = str(active(os.environ.get('GITHUB_EVENT_NAME','workflow_dispatch'),
                       datetime.now(ZoneInfo('Australia/Brisbane')))).lower()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        f.write('active='+value+'\n')
    print('Schedule window active:',value)
