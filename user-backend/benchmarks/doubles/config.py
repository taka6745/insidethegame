"""The seeded configuration (migrations 016, 019, 022, 037 and 040), for in-process doubles without a database."""
import importlib.util
import json
import re
from pathlib import Path

from backend.models.config import CONFIGS

SEEDS = [Path(__file__).resolve().parents[2] / 'migrations' / name
         for name in ('016_config.sql', '019_prices_and_stream_gaps.sql')]


def seeded(name):
    if name in ('cross-match', 'follow-offer'):
        module = migration('040_cross_match')
        return CONFIGS[name].model_validate(module.CONFIG if name == 'cross-match' else module.OFFER)
    text = ''.join(seed.read_text() for seed in SEEDS)
    match = re.search(r"VALUES \('" + re.escape(name) + r"', '(.*?)'::jsonb\)", text, re.S)
    document = json.loads(match.group(1))
    if name == 'replay-timing':
        document = {**migration('022_spadl_replay_timing').remap(document),
                    'playback': migration('037_replay_playback').PLAYBACK}
    return CONFIGS[name].model_validate(document)


def migration(name):
    spec = importlib.util.spec_from_file_location('migration_' + name[:3], SEEDS[0].with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeededConfig:
    """ConfigService's read interface over the seed."""
    async def get(self, name):
        return seeded(name)
