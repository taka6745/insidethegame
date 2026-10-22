"""Deterministic replay cut points. The agent picks evidence; code picks seconds."""
from dataclasses import dataclass, field

# Timing, lead-ins and page limits are configuration (models/config.Replay, `replay` row).


class ReplayPlanError(ValueError):
    """A plan cited unknown or unobserved evidence."""


@dataclass
class Clip:
    start: float
    end: float
    source_ids: list[str] = field(default_factory=list)
    captions: list[str] = field(default_factory=list)
    marks: list[float] = field(default_factory=list)  # Event moments, for the progress bar.

    @property
    def seconds(self):
        return self.end - self.start


def window(item, events, moments, possession_starts, config):
    """One item's [start, end) in video seconds before clamping."""
    if item["kind"] == "key_moment":
        moment = moments.get(item["source_id"])
        if moment is None:
            raise ReplayPlanError(f"Unknown key moment {item['source_id']}")
        end = moment["end_video_seconds"]
        goals = [events[i]["video_seconds"] for i in moment.get("event_ids") or []
                 if i in events and events[i]["event_type"] == "goal"]
        if goals:  # Same short after as a goal clip, whatever the authored window says.
            end = min(end, max(goals) + config.timing.get("goal", config.default)[1])
        return moment["start_video_seconds"], end, moment["period"]
    event = events.get(item["source_id"])
    if event is None:
        raise ReplayPlanError(f"Unknown or unobserved event {item['source_id']}")
    before, after = config.timing.get(event["event_type"], config.default)
    at = event["video_seconds"]
    lead = item.get("lead_in", "normal")
    if lead == "move":
        start = possession_starts.get(event.get("possession_id"), at - before) - 1.0
        start = max(start, at - config.max_move_seconds)
    else:
        start = at - before * config.lead_in[lead]
    return start, at + after, event["period"]


def plan_clips(items, *, events, moments, periods, observed_video, config, possession_starts=None, page=0):
    """Clips for one page of ranked items, in playback (chronological) order.

    events: id -> {video_seconds, event_type, period, possession_id}, already bounded to the
    viewer's observed prefix. periods: period -> (start_video, end_video or None while live).
    Overlapping windows merge into one clip first, so no footage repeats across pages; clips
    then fill pages in rank order up to config.max_clips clips and config.max_seconds. Returns (clips, total_items, page_count).
    """
    possession_starts = possession_starts or {}
    clips = []  # (rank, clip)
    for rank, item in enumerate(items):
        start, end, period = window(item, events, moments, possession_starts, config)
        first, last = periods.get(period, (0.0, None))
        start = max(start, first, 0.0)
        end = min(end, observed_video, last if last is not None else observed_video, start + config.max_seconds)
        if end <= start:
            continue  # Not yet observed or outside its period: nothing to show.
        ids = (moments[item["source_id"]].get("event_ids") or []) if item["kind"] == "key_moment" else [item["source_id"]]
        marks = sorted(events[i]["video_seconds"] for i in ids if i in events and start <= events[i]["video_seconds"] <= end)
        clips.append((rank, Clip(start, end, [item["source_id"]], [item["caption"]], marks)))
    merged = []  # [best rank, clip]
    for rank, clip in sorted(clips, key=lambda pair: pair[1].start):
        last = merged[-1][1] if merged else None
        if last and clip.start <= last.end + config.merge_gap and max(last.end, clip.end) - last.start <= config.max_seconds:
            last.end = max(last.end, clip.end)
            last.source_ids += clip.source_ids
            last.captions += clip.captions
            last.marks = sorted(last.marks + clip.marks)
            merged[-1][0] = min(merged[-1][0], rank)
        else:
            merged.append([rank, clip])
    pages, current, seconds = [], [], 0.0
    for _, clip in sorted(merged, key=lambda pair: pair[0]):
        if current and (len(current) == config.max_clips or seconds + clip.seconds > config.max_seconds):
            pages.append(current)
            current, seconds = [], 0.0
        current.append(clip)
        seconds += clip.seconds
    if current:
        pages.append(current)
    chosen = pages[page] if page < len(pages) else []
    return sorted(chosen, key=lambda clip: clip.start), len(items), max(1, len(pages))
