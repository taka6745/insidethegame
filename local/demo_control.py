"""Control the shared forward-only demo through the user-backend API."""
import argparse
import os
import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['reset', 'start'])
parser.add_argument('--from-minute', type=float, default=0, help='Start a fresh run this far into the match')
args = parser.parse_args()
base = os.getenv('BACKEND_URL', 'http://backend:8000')
path = '/product/demo/reset' if args.action == 'reset' else '/lab/replay/start'
body = {} if args.action == 'reset' else {'interval_ms': 1100, 'from_seconds': args.from_minute * 60}
response = httpx.post(base + path, json=body, timeout=60)
response.raise_for_status()
print('Match ready' if args.action == 'reset' else 'Replay started; recorded timestamps control playback')
