"""Fixed followed topics for tests and devtools only. The service always reads the user backend's
(follows.topics.HttpTopicSource); CONFIG mirrors the backend's seeded `subscriptions` tunables."""
from narrative_engine.follows.topics import FollowTargets

CONFIG = {
    "decision": {"instructions": "How far does this update move the followed story?",
                 "levels": ["It does not touch the story", "It touches the story without changing it",
                            "It moves the story on", "It is a turning point for the story"],
                 "trigger_level": 2, "min_confidence": 0.3},
    "novelty": {"enabled": True, "min_probability": 0.5,
                "instructions": "Is this update a new development compared with the last update the viewer got?"},
    "prefilter": {"minute_recaps": True, "key_events": True, "storyline_updates": True},
    "limits": {"min_minutes_between_narratives": 1, "max_topics_per_match": 50, "planner_turns_per_minute": 6,
               "follow_changes_per_minute": 4, "planner_context_turns": 6, "period_end_wrap_up": True,
               "pivotal_key_types": ["Goal", "OwnGoal", "RedCard", "PenaltyAwarded", "PenaltyMissed", "VarOverturn"]},
    "catch_up": {"reason": "A viewer has just started following this story and has not seen it so far.",
                 "retries": 2},
    "clips": {"enabled": True,
              "key_types": ["Goal", "OwnGoal", "RedCard", "PenaltyAwarded", "PenaltyMissed", "VarOverturn"],
              "instructions": "How much would this story's followers want to watch this moment as a clip?",
              "levels": ["Not at all", "A little", "Quite a lot", "They would want to see it"],
              "min_level": 3, "min_confidence": 0.5,
              "timing": {"goal": "goal", "own_goal": "goal", "penalty": "foul", "penalty_missed": "shot_penalty",
                         "red_card": "card", "second_yellow": "card", "var_overturn": "goal"},
              "max_items": 12, "always_for": [], "shared": True},
}


def topic(topic_id, kind, buckets, created_seq=0, **spec):
    return {"topic_id": topic_id, "created_seq": created_seq, "followers": len(buckets), "buckets": list(buckets),
            "spec": {"kind": kind, "storyline_id": None, "team_id": None, "player_id": None, "focus": "",
                     "label": spec.get("label", topic_id), **spec}}


class StaticTopics:
    """`topics` may be changed between calls; each change is a new revision."""

    def __init__(self, topics=(), config=None):
        self.config = dict(config or CONFIG)
        self.topics, self.revision = list(topics), 1

    def set(self, topics):
        self.topics, self.revision = list(topics), self.revision + 1

    async def current(self, match_id):
        return FollowTargets(self.revision, 1, self.config, tuple(self.topics))
