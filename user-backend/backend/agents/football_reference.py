"""Small reviewed rules reference, replaceable independently of agent prompts."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_reference():
    return json.loads((Path(__file__).parent / 'knowledge' / 'football-basics.json').read_text())
