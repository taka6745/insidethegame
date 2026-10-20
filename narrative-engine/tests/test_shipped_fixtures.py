"""The committed narrative fixtures bind to the committed recording, byte for byte."""
import hashlib
import json
from pathlib import Path

import pytest

from narrative_demo.models.fixtures import NarrativeFixture

ROOT = Path(__file__).resolve().parents[2]
RECORDING = ROOT / 'data-generation/recordings/chelsea-united-grf.json'


@pytest.mark.skipif(not RECORDING.exists(), reason='Run from the repository checkout')
def test_fixtures_bind_to_the_shipped_recording_and_cover_every_broadcast_minute():
    recording = RECORDING.read_bytes()
    fixture = NarrativeFixture.model_validate_json((ROOT / 'narrative-engine/fixtures/grf-narratives.json').read_text())
    assert fixture.recording_hash == hashlib.sha256(recording).hexdigest()
    labels = [minute.label for minute in fixture.minutes]
    assert labels[0] == "1'" and "45+1'" in labels and labels[-1] == "90+1'"
    assert len(fixture.minutes) == 92 and all(len(minute.narratives) == 12 for minute in fixture.minutes)
    assert {tier.tier for tier in fixture.tiers} == {'five-minute', 'twenty-minute', 'half'}
    events = {event['eventId'] for event in json.loads(recording)['events']}
    assert all(set(moment.event_ids) <= events for moment in fixture.key_moments)
