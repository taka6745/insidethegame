"""Story follows (local/contracts.md §8b): topics, subscriptions, delivered narratives, follow chat, tunables, prompts.

- `subscription_topics`: one generation unit per identical follow per match (shared by its followers).
- `subscriptions`: a viewer's (conversation's) follows; at most one active per viewer (one per profile and match).
- `subscription_revisions`: bumped by every change the engine's subscription-targets read depends on.
- `subscription_narratives`: the engine's `kind: subscription` narratives as delivered, per topic and bucket.
- `question_turns.channel`: the follow chat reuses the question tables (`follow` turns), with a timestamp for limits.
Every table is match-scoped and purged with the match. Config rows `subscriptions` and `key-moment-feed` are
tunables (/dev/config). Roles subscription-planner, subscription-decision and subscription-author are seeded from
migrations/prompts/ (a fresh store gets them at startup, repositories/prompts.py).
"""
import json
from pathlib import Path

from psycopg.types.json import Jsonb

SEEDS = Path(__file__).parent / 'prompts'
ROLES = ('subscription-planner', 'subscription-decision', 'subscription-author')
FILES = {'subscription-decision': 'subscription-decision.v1.txt',  # v2: 029
         'subscription-planner': 'subscription-planner.v1.txt'}  # v2: 042

DDL = '''
ALTER TABLE question_turns ADD COLUMN IF NOT EXISTS channel text NOT NULL DEFAULT 'questions'
    CHECK (channel IN ('questions', 'follow'));
ALTER TABLE question_turns ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS question_turns_channel ON question_turns (conversation_id, channel, created_at);

CREATE TABLE subscription_topics (
    match_id text NOT NULL REFERENCES received_matches(match_id) ON DELETE CASCADE,
    topic_id text NOT NULL,
    spec jsonb NOT NULL,
    created_seq integer NOT NULL CHECK (created_seq >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, topic_id)
);
CREATE TABLE subscriptions (
    id uuid PRIMARY KEY,
    match_id text NOT NULL,
    conversation_id uuid NOT NULL REFERENCES question_conversations(id) ON DELETE CASCADE,
    topic_id text NOT NULL,
    spec jsonb NOT NULL,
    since_seq integer NOT NULL CHECK (since_seq >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    FOREIGN KEY (match_id, topic_id) REFERENCES subscription_topics (match_id, topic_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX subscriptions_one_active ON subscriptions (conversation_id) WHERE ended_at IS NULL;
CREATE INDEX subscriptions_active_topic ON subscriptions (match_id, topic_id) WHERE ended_at IS NULL;
CREATE TABLE subscription_revisions (
    match_id text PRIMARY KEY REFERENCES received_matches(match_id) ON DELETE CASCADE,
    revision integer NOT NULL CHECK (revision > 0)
);
CREATE TABLE subscription_narratives (
    id text PRIMARY KEY,
    match_id text NOT NULL,
    topic_id text NOT NULL,
    bucket_id text NOT NULL,
    seq integer NOT NULL,
    step_id text NOT NULL,
    period integer NOT NULL,
    time_min integer NOT NULL,
    time_sec integer NOT NULL,
    clock_seconds integer NOT NULL,
    event_seq integer,
    text text NOT NULL,
    trigger jsonb NOT NULL,
    decision jsonb,
    storyline_ids jsonb NOT NULL DEFAULT '[]',
    prompt_version text,
    tokens jsonb,
    created_at text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (match_id, topic_id) REFERENCES subscription_topics (match_id, topic_id) ON DELETE CASCADE
);
CREATE INDEX subscription_narratives_feed ON subscription_narratives (match_id, topic_id, bucket_id, period, clock_seconds);
'''

# The developer's wording (22 Oct): "Goal · {team} · {scorer}", "Red card · {player}", "Half time · {score}".
LABELS = {'goal': 'Goal · {team} · {scorer}', 'own_goal': 'Own goal · {subject}', 'red_card': 'Red card · {player}',
          'second_yellow': 'Second yellow · {player}', 'penalty': 'Penalty · {team}',
          'penalty_missed': 'Penalty missed · {subject}', 'var_overturn': 'VAR · goal ruled out · {team}',
          'kick_off': 'Kick-off', 'half_time': 'Half time · {score}', 'second_half': 'Second half',
          'full_time': 'Full time · {score}', 'period_start': 'Period {period} begins',
          'period_end': 'Period {period} ends'}
SCORE = '{home} {home_goals}–{away_goals} {away}'

CONFIG = {
    # Decision-1 answers `decision` per followed topic on each update the prefilter lets through; a score at or
    # above trigger_level with at least min_confidence triggers that topic's narrative. Permissive defaults.
    'subscriptions': {
        'decision': {'instructions': 'How far does this update move the followed story?',
                     'levels': ['It does not touch the story', 'It touches the story without changing it',
                                'It moves the story on', 'It is a turning point for the story'],
                     'trigger_level': 2, 'min_confidence': 0.3},
        # Light firing guard: a minimum match-time gap per topic (pivotal moments bypass it) and a novelty check.
        'novelty': {'enabled': True, 'min_probability': 0.5,
                    'instructions': 'Is this update a new development compared with the last update the viewer got?'},
        'prefilter': {'minute_recaps': True, 'key_events': True, 'storyline_updates': True},
        # The trigger reason of a viewer's "story so far" step (029).
        'catch_up': {'reason': 'A viewer has just started following this story and has not seen it so far.',
                     # A story so far dropped as ungrounded is tried again at later horizons (032).
                     'retries': 2},
        'limits': {'min_minutes_between_narratives': 1, 'max_topics_per_match': 50,
                   'planner_turns_per_minute': 6, 'follow_changes_per_minute': 4, 'planner_context_turns': 6,
                   # Half and full time give every follow of the match a wrap-up, without a decision (030).
                   'period_end_wrap_up': True,
                   'pivotal_key_types': ['Goal', 'OwnGoal', 'RedCard', 'PenaltyAwarded', 'PenaltyMissed', 'VarOverturn']},
        'suggestions': {'max_items': 4, 'storylines': True, 'min_storyline_salience': 0.3, 'teams': True,
                        'players': True},
        'min_name_match': 0.5,
        # Entities offered back when a follow-chat name is ambiguous (031).
        'max_candidates': 4,
        # Moment clips in a follow's playlist (038): asked with `decision` on these key events only.
        'clips': {'enabled': True,
                  'key_types': ['Goal', 'OwnGoal', 'RedCard', 'PenaltyAwarded', 'PenaltyMissed', 'VarOverturn'],
                  'instructions': "How relevant is this moment to the story these viewers follow?",
                  'levels': ['Not relevant', 'Slightly relevant', 'Relevant', 'Central to the story'],
                  'min_level': 3, 'min_confidence': 0.5,
                  'timing': {'goal': 'goal', 'own_goal': 'goal', 'penalty': 'foul', 'penalty_missed': 'shot_penalty',
                             'red_card': 'card', 'second_yellow': 'card', 'var_overturn': 'goal'},
                  'max_items': 12, 'always_for': [], 'shared': True}},
    # Pivotal moments every feed shows (developer decision D4, 21 Oct): goals with the scorer, red cards and second
    # yellows, penalties, VAR overturns, kick-off, half-time and full-time.
    'key-moment-feed': {
        'kinds': ['goal', 'own_goal', 'red_card', 'second_yellow', 'penalty', 'penalty_missed', 'var_overturn',
                  'kick_off', 'half_time', 'full_time'],
        'labels': LABELS, 'subject_with_player': '{player} ({team})', 'score': SCORE},
}


def migrate(conn):
    from backend.models.prompts import placeholders
    conn.execute(DDL)
    for name, document in CONFIG.items():
        conn.execute('INSERT INTO backend_config (name, document) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                     (name, Jsonb(json.loads(json.dumps(document)))))
    if not conn.execute('SELECT 1 FROM narrative_prompt_active LIMIT 1').fetchone():
        return  # Fresh store: startup seeds every role as version 1.
    for role in ROLES:
        template = (SEEDS / FILES.get(role, f'{role}.txt')).read_text(encoding='utf-8')
        conn.execute("INSERT INTO narrative_prompts (role, version, template, placeholders, source) "
                     "VALUES (%s, 1, %s, %s, 'seed') ON CONFLICT DO NOTHING", (role, template, placeholders(template)))
        conn.execute("INSERT INTO narrative_prompt_active (role, version, revision) "
                     "SELECT %s, 1, max(revision) + 1 FROM narrative_prompt_active ON CONFLICT DO NOTHING", (role,))
