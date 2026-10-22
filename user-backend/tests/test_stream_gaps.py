"""A missing seq (e.g. one invalid MatchEvent) never blocks a match forever: later events wait,
the gap is reported, then recovered from ETL's canonical event or skipped with a placeholder."""
import json

from backend.adapters.match_stream import handle_match_message
from backend.services.observed import observed
from harness import MATCH, Running, Upstream


def envelope(run, seq):
    event = run.upstream.matches[MATCH].event(seq).model_dump(mode='json')
    return json.dumps({'type': 'MatchEvent', 'version': 2, 'matchId': MATCH, 'seq': seq, 'synthetic': True, 'event': event})


def deliver(run, *seqs, position=100):
    for seq in seqs:
        run.client.portal.call(handle_match_message, envelope(run, seq), ('0', position + seq), run.registry)


def recover(run, timeout=30, aged=0):
    match = run.match()
    if match.gap_since is not None:
        match.gap_since -= aged
    run.client.portal.call(run.registry.recover_gaps, run.upstream.dab.canonical_event, timeout)


def test_events_after_a_gap_wait_and_the_gap_is_reported_and_holds_the_checkpoint(store):
    with Running(store) as run:
        run.send(3)
        stored = run.registry.repository.checkpoints()
        deliver(run, 5, 6)
        assert run.match().seq == 3 and sorted(run.match().pending) == [5, 6]
        [gap] = run.client.get('/health').json()['gaps']
        assert gap['match_id'] == MATCH and gap['seq'] == 4 and gap['pending'] == 2 and gap['state'] == 'open'
        pipeline = run.client.get('/dev/pipeline').json()
        assert pipeline['services'][0]['status'] == 'degraded' and pipeline['gaps'][0]['seq'] == 4
        # A restart must replay the held events, so the stream position stays put.
        assert run.registry.repository.checkpoints() == stored
        recover(run, aged=5)  # Younger than the timeout: keep waiting.
        assert run.match().seq == 3
        deliver(run, 4)  # The late event drains the held ones.
        assert run.match().seq == 6 and not run.match().pending and run.registry.gaps() == []
        assert run.registry.repository.checkpoints()['0'] == 104
        assert run.client.get('/dev/pipeline').json()['services'][0]['status'] == 'ok'


def test_a_timed_out_gap_is_recovered_from_etl_canonical_events(store):
    upstream = Upstream()
    upstream.canonical = True
    with Running(store, upstream=upstream) as run:
        run.send(3)
        deliver(run, 5, 6)
        recover(run, aged=31)
        match = run.match()
        assert match.seq == 6 and match.events[3] == run.upstream.matches[MATCH].event(4)
        [row] = run.client.get('/dev/pipeline').json()['gaps']
        assert (row['match_id'], row['seq'], row['state']) == (MATCH, 4, 'recovered') and row['blocked_seconds'] >= 31


def test_without_etl_canonical_events_the_gap_is_skipped_and_survives_restart(store):
    upstream = Upstream()
    with Running(store, upstream=upstream) as run:
        run.send(3)
        deliver(run, 5, 6)
        recover(run, aged=31)  # ETL cannot answer: one more timeout before skipping.
        assert run.match().seq == 3
        recover(run, aged=30)
        match = run.match()
        assert match.seq == 6 and run.registry.gaps() == [] and run.client.get('/health').json()['gaps'] == []
        placeholder = match.events[3]
        assert placeholder.event_id == 'gap-4' and placeholder.deleted and placeholder.sequence == 4
        assert placeholder.match_time_seconds == match.events[2].match_time_seconds
        # Counted by nothing: the observed history equals the feed's events without seq 4.
        feed = [run.upstream.matches[MATCH].event(s) for s in (1, 2, 3, 5, 6)]
        assert observed(match.events) == observed(feed)
        assert run.client.get('/dev/pipeline').json()['gaps'][0]['state'] == 'skipped'
        deliver(run, 4)  # A late original is a redelivery now; the first commit stays.
        assert run.match().events[3].event_id == 'gap-4'
    with Running(store, upstream=upstream, matches=()) as run:
        assert run.match().seq == 6 and run.match().events[3].event_id == 'gap-4'
        assert run.client.post('/admin/matches/purge', json={'match_id': MATCH}).json()['purged']['match_gaps'] == 1



def test_a_lagging_etl_gets_another_timeout_and_a_later_gap_its_own(store):
    upstream = Upstream()
    upstream.canonical = True
    upstream.canonical_missing = {4}
    with Running(store, upstream=upstream) as run:
        run.send(3)
        deliver(run, 5, 6, 8)
        recover(run, aged=31)  # No row and ETL's watermark (3) is before seq 4: it may still arrive.
        assert run.match().seq == 3
        upstream.matches[MATCH].committed = 8  # ETL is past seq 4 without a row: skip it.
        recover(run)
        assert run.match().seq == 6 and run.match().events[3].event_id == 'gap-4'
        [gap] = run.registry.gaps()  # Seq 7 is missing now; its timeout starts here.
        assert gap['seq'] == 7 and gap['age_seconds'] < 30
        recover(run)
        assert run.match().seq == 6


def test_a_purge_during_recovery_never_revives_the_match(store):
    upstream = Upstream()
    upstream.canonical = True
    with Running(store, upstream=upstream) as run:
        run.send(3)
        deliver(run, 5)
        run.match().gap_since -= 31

        async def fetch(match_id, seq):
            event = await upstream.dab.canonical_event(match_id, seq)
            await run.registry.purge(match_id)
            return event

        run.client.portal.call(run.registry.recover_gaps, fetch, 30)
        assert run.registry.gaps() == [] and MATCH not in run.registry.matches
        assert run.registry.repository.load(MATCH) == ([], []) and run.registry.repository.gaps() == []
