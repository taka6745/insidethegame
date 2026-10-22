import pytest

from backend.adapters.hls_media import parse_segments
from backend.services.replay_clips import ReplayPlanError, plan_clips
from benchmarks.doubles.config import seeded

PERIODS = {1: (0.0, 2800.0), 2: (2800.0, None)}


def event(identifier, at, kind="pass", period=1, possession=None):
    return identifier, {"video_seconds": at, "event_type": kind, "period": period, "possession_id": possession}


def plan(items, events, observed=4000.0, **kwargs):
    return plan_clips(items, events=dict(events), moments=kwargs.pop("moments", {}), periods=PERIODS,
                      observed_video=observed, config=kwargs.pop('config', seeded('replay-timing')), **kwargs)


def item(source, caption="c", lead="normal", kind="event"):
    return {"source_id": source, "kind": kind, "caption": caption, "lead_in": lead}


def test_type_table_default_and_lead_in_scaling():
    events = [event("g", 100, "goal"), event("i", 300, "interception"), event("s", 600, "shot")]
    clips, total, pages = plan([item("g"), item("i"), item("s", lead="long")], events)
    assert [(c.start, c.end) for c in clips] == [(90, 105), (294, 302), (588, 603)]  # i: widened to min_clip_seconds
    assert (total, pages) == (3, 1)


def test_move_lead_in_starts_at_possession_gain_with_a_cap():
    events = [event("g", 500, "goal", possession=7), event("h", 900, "goal", possession=8)]
    clips, *_ = plan([item("g", lead="move"), item("h", lead="move")], events,
                     possession_starts={7: 488.0, 8: 800.0})
    assert [(c.start, c.end) for c in clips] == [(487, 505), (875, 905)]


def test_overlapping_clips_merge_and_keep_both_captions():
    events = [event("a", 100, "shot"), event("b", 104, "keeper_save")]
    clips, *_ = plan([item("a", "Shot"), item("b", "Save")], events)
    assert len(clips) == 1
    assert (clips[0].start, clips[0].end, clips[0].captions) == (94, 107, ["Shot", "Save"])


def test_clamped_to_period_and_observed_position_never_future():
    events = [event("late", 2795, "goal"), event("live", 3990, "goal", period=2)]
    clips, *_ = plan([item("late"), item("live")], events, observed=3992.0)
    assert [(c.start, c.end) for c in clips] == [(2785, 2800), (3980, 3992)]


def test_unknown_or_unobserved_evidence_is_rejected():
    with pytest.raises(ReplayPlanError):
        plan([item("missing")], [])
    with pytest.raises(ReplayPlanError):
        plan([item("km", kind="key_moment")], [])


def test_key_moment_uses_its_authored_window():
    moments = {"km": {"start_video_seconds": 200.0, "end_video_seconds": 230.0, "period": 1}}
    clips, *_ = plan([item("km", kind="key_moment")], [], moments=moments)
    assert (clips[0].start, clips[0].end) == (200, 230)


def test_pages_fill_by_rank_within_twelve_clips_and_three_minutes_and_lose_nothing():
    events = [event(f"e{i}", 100 + i * 60, "goal") for i in range(30)]
    items = [item(f"e{i}", lead="long") for i in reversed(range(30))]  # Ranked latest first.
    clips, total, pages = plan(items, events)
    assert (len(clips), total, pages) == (7, 30, 5)  # 7 x 25 s fits in 180 s.
    assert [c.source_ids[0] for c in clips] == [f"e{i}" for i in range(23, 30)]  # Top ranked, in time order.
    shown = [c.source_ids[0] for p in range(pages) for c in plan(items, events, page=p)[0]]
    assert sorted(shown) == sorted(f"e{i}" for i in range(30))
    passes = [event(f"p{i}", 100 + i * 60) for i in range(13)]
    assert plan([item(f"p{i}") for i in range(13)], passes)[2] == 2  # 12-clip cap.
    assert plan(items, events, page=9)[0] == []


def test_goal_key_moments_end_shortly_after_the_goal_and_clips_mark_their_events():
    moments = {"km": {"start_video_seconds": 480.0, "end_video_seconds": 530.0, "period": 1,
                      "event_ids": ["shot", "g"]}}
    events = [event("shot", 490, "shot"), event("g", 500, "goal")]
    clips, *_ = plan([item("km", kind="key_moment")], events, moments=moments)
    assert (clips[0].start, clips[0].end, clips[0].marks) == (480, 505, [490, 500])
    merged, *_ = plan([item("shot"), item("g")], events)
    assert merged[0].marks == [490, 500]


def test_segment_uris_must_stay_in_the_media_directory():
    for uri in ("../secret.ts", "/etc/passwd", "sub/0.ts"):
        with pytest.raises(ValueError):
            parse_segments(f"#EXTM3U\n#EXTINF:2.0,\n{uri}\n")


def test_overlapping_windows_never_split_across_pages():
    # Thirteen near-simultaneous events: one merged clip, not a 12 + 1 split that replays footage.
    events = [event(f"t{i}", 100 + i * 0.5, "tackle") for i in range(13)]
    clips, total, pages = plan([item(f"t{i}") for i in range(13)], events)
    assert (len(clips), total, pages) == (1, 13, 1)
    assert len(clips[0].source_ids) == 13
