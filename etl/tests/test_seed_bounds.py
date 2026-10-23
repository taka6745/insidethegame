"""A demo seed may hold nothing from past its seq, in any table it restores."""
from local_stream.demo_seeds import past_seq

SEED = {
    "canonicalEvents": [{"seq": 9, "periodId": 1, "matchTimeSeconds": 1199}],
    "rawEvents": [{"id": 101, "eventSeq": 9, "periodId": 1, "timeMin": 19}],
    "spadlActions": [{"seq": 8, "finalSeq": 9}],
    "possessionSamples": [{"sampleId": 1, "eventSeq": 9}, {"sampleId": 2, "eventSeq": None}],
    "keyEvents": [{"id": 101}],
    "minuteStats": [{"periodId": 1, "timeMin": 19}],
}


def test_a_seed_within_its_seq_passes():
    assert past_seq(SEED, 9) is None


def test_every_restored_table_is_bounded():
    assert past_seq({**SEED, "spadlActions": [{"seq": 8, "finalSeq": 10}]}, 9) == "spadlActions"
    assert past_seq({**SEED, "possessionSamples": [{"eventSeq": 10}]}, 9) == "possessionSamples"
    assert past_seq({**SEED, "keyEvents": [{"id": 102}]}, 9) == "keyEvents"  # not one of the seeded MA3 rows
    assert past_seq({**SEED, "minuteStats": [{"periodId": 1, "timeMin": 20}]}, 9) == "minuteStats"
