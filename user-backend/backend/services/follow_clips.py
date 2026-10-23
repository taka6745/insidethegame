"""Moment playlists: the key moments clipped for a followed topic (Decision-1, or clip-on
from creation) or for a bucket's shared narratives (key-event clips), cut like replay clips (replay-timing) on the
match's own stream and bounded to the viewer's snapshot. Each clip carries its moments' facts for its preview card."""
from backend.services.replay_clips import plan_clips

CARD_FIELDS = ('id', 'kind', 'period', 'clock_seconds', 'minute_label', 'label', 'team_id', 'team_name',
               'player_name', 'score')


def moment_playlists(clips, facts, moments, periods, observed, timing, config, stream_url):
    """{key: replay} in the chat replay's shape (one page, chronological); key is a topic or bucket id.

    clips: {key: [moment_id]} (repositories). facts: adapters/ma3.key_moment rows at the snapshot. moments: the
    snapshot's feed moments (services/key_moments.feed_moments), by id. periods: period -> (start, end) video
    seconds. observed: the snapshot's video seconds. timing: models/config.Replay. config: models/config.FollowClips
    (`timing`: which kinds clip, and with which replay-timing key). stream_url: the match's published stream, or
    None without footage (cut points only)."""
    by_id = {f['id']: f for f in facts}
    out = {}
    for key, moment_ids in clips.items():
        events, items = {}, []
        for moment_id in moment_ids:
            fact = by_id.get(moment_id)
            kind = fact and config.timing.get(fact['kind'])
            if not kind or fact.get('video_seconds') is None:
                continue  # not at this snapshot yet, not a clipped kind, or no footage time
            events[moment_id] = {'video_seconds': fact['video_seconds'], 'event_type': kind, 'period': fact['period']}
            label = (moments.get(moment_id) or {}).get('label', '')
            items.append({'kind': 'event', 'source_id': moment_id, 'caption': label})
        if not items:
            continue
        # Ranked newest first, so when the reel's limits (max_clips, max_seconds) cut, the oldest go; played in order.
        found, total, page_count = plan_clips(items[::-1], events=events, moments={}, periods=periods,
                                              observed_video=observed or 0.0, config=timing)
        if not found:
            continue
        replay = {'page': 0, 'page_size': timing.max_clips, 'total_items': total, 'page_count': page_count,
                  'truncated': page_count > 1,  # no `observed_until`: it would rebuild the card every snapshot
                  'clips': [{'start': round(c.start, 3), 'end': round(c.end, 3), 'source_ids': c.source_ids,
                             'captions': c.captions, 'marks': [round(m, 3) for m in c.marks],
                             'moments': [{f: moments[i].get(f) for f in CARD_FIELDS}
                                         for i in c.source_ids if i in moments]} for c in found],
                  'seconds': round(sum(c.seconds for c in found), 3), 'playlist': stream_url,
                  'playback': timing.playback.model_dump()}  # the reel's transitions and slow motion
        if stream_url:
            for clip in replay['clips']:
                clip['playlist_start'], clip['playlist_end'] = clip['start'], clip['end']
        out[key] = replay
    return out


follow_playlists = moment_playlists  # a followed topic's playlist
