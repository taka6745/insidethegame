"""Tunables served and edited under /dev/config/{table}; seeded by migrations/016_config.sql."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

StatTemplate = Annotated[str, Field(pattern=r'^(all|\{team\}):[a-z_]{1,40}$')]
Seconds = Annotated[float, Field(ge=0, le=600)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StatsBySupport(Strict):
    team: list[StatTemplate] = Field(min_length=1, max_length=20)
    neutral: list[StatTemplate] = Field(min_length=1, max_length=20)

    def resolve(self, support):
        """Stat ids for a contestant id, or `neutral`."""
        rows = self.neutral if support == 'neutral' else self.team
        return [row.replace('{team}', support) for row in rows]


class Presentation(Strict):
    card_slots: int = Field(ge=1, le=8)
    default_stats: StatsBySupport
    fallback_stats: StatsBySupport
    # Never shown as a default card (both teams' possession is 100% by definition).
    excluded_stats: list[Annotated[str, Field(pattern=r'^[a-z0-9_-]{1,64}:[a-z_]{1,40}$')]] = Field(max_length=50)
    # Tracked stats displace lower-priority defaults, never these kinds.
    protected_stat_kinds: list[Annotated[str, Field(pattern=r'^[a-z_]{1,40}$')]] = Field(max_length=10)
    # Newest shared narratives kept per bucket in each snapshot (a 92-minute match writes about 100 per bucket).
    narratives_per_bucket: int = Field(default=200, ge=1, le=1000)


class Transitions(Strict):
    """Between clips of a reel: hold the last frame, then the sting video fades in over the paused picture, the
    cut happens under it, and it fades out as the next clip plays (viewer, migrations/037)."""
    enabled: bool
    hold_seconds: float = Field(ge=0, le=5)
    # A video under /assets/, or `builtin:<name>` for a sting the viewer draws itself (migrations/049).
    asset: Annotated[str, Field(pattern=r'^(/assets/[a-z0-9/_-]{1,120}\.(mp4|webm)|builtin:[a-z-]{1,40})$')]
    asset_start_seconds: float = Field(ge=0, le=10)  # where in the asset the sting starts
    sting_seconds: float = Field(gt=0, le=10)        # how long it shows, fades included
    cut_seconds: float = Field(ge=0, le=10)          # into the sting: the next clip is cued while covered
    fade_seconds: float = Field(ge=0, le=2)          # fade in and fade out of the sting layer

    @model_validator(mode='after')
    def cut_inside(self):
        # The cut happens once the sting has faded in, and before it starts fading out.
        if not self.fade_seconds <= self.cut_seconds <= self.sting_seconds - self.fade_seconds:
            raise ValueError('cut_seconds must fall between the fade in and the fade out of sting_seconds')
        return self


class SlowMotion(Strict):
    """Playback slows around each clip's marked events: eased in over ramp_seconds, held at `rate` from
    before_seconds ahead of the event to after_seconds past it, eased out over ramp_seconds (viewer)."""
    enabled: bool
    rate: float = Field(ge=0.1, le=1)
    ramp_seconds: float = Field(ge=0, le=5)
    before_seconds: float = Field(ge=0, le=10)
    after_seconds: float = Field(ge=0, le=10)


class Playback(Strict):
    """Served with every replay as `playback`; the viewer skips both under prefers-reduced-motion."""
    transitions: Transitions
    slow_motion: SlowMotion


class Replay(Strict):
    # Seconds before/after a moment, keyed by SPADL action type, `goal` (a scoring shot) or `card`.
    timing: dict[Annotated[str, Field(pattern=r'^[a-z_]{1,40}$')], tuple[Seconds, Seconds]] = Field(max_length=60)
    default: tuple[Seconds, Seconds]
    lead_in: dict[str, Annotated[float, Field(ge=0, le=5)]]
    max_clips: int = Field(ge=1, le=50)
    max_seconds: float = Field(gt=0, le=1800)
    max_move_seconds: float = Field(gt=0, le=120)
    # The shortest clip: a short lead-in on a quick action still shows enough to follow (046).
    min_clip_seconds: float = Field(default=0.0, ge=0, le=60)
    merge_gap: float = Field(ge=0, le=30)
    max_items: int = Field(ge=1, le=36)  # QuestionDraft.replay_items accepts at most 36.
    playback: Playback  # 037

    @model_validator(mode='after')
    def lead_ins(self):
        if set(self.lead_in) != {'short', 'normal', 'long'}:
            raise ValueError('lead_in needs exactly short, normal and long')
        return self


class KeyMoments(Strict):
    ranks: dict[Annotated[str, Field(pattern=r'^(goal|dismissal|penalty|card)$')], Annotated[int, Field(ge=1, le=100)]]

    @model_validator(mode='after')
    def every_kind(self):
        if set(self.ranks) != {'goal', 'dismissal', 'penalty', 'card'}:
            raise ValueError('ranks needs goal, dismissal, penalty and card')
        return self

    def rank(self, kind):
        """kind: goal | dismissal | penalty | card (adapters/engine_history.key_kind)."""
        return self.ranks[kind]


class Prices(Strict):
    """US dollars per million tokens for viewer receipts; never a provider's price list."""
    input: float = Field(ge=0, le=1000)
    output: float = Field(ge=0, le=1000)


class Stream(Strict):
    # A missing seq older than this is recovered from ETL or skipped.
    gap_timeout_seconds: float = Field(ge=1, le=3600)


Text = Annotated[str, Field(min_length=1, max_length=300)]


class FollowDecision(Strict):
    """The score question Decision-1 answers per followed topic on each update (served to the engine)."""
    instructions: Text
    levels: list[Text] = Field(min_length=2, max_length=10)
    trigger_level: int = Field(ge=1, le=9)    # a score at or above this level triggers a narrative
    min_confidence: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def level_in_range(self):
        if self.trigger_level >= len(self.levels):
            raise ValueError('trigger_level must name one of the levels')
        return self


class FollowNovelty(Strict):
    """A yes/no question Decision-1 answers per triggered topic, with the topic's last narrative in the state;
    the topic fires only when P(yes) is at least min_probability."""
    enabled: bool
    instructions: Text
    min_probability: float = Field(ge=0, le=1)


KEY_TYPES = ('Goal', 'OwnGoal', 'VarOverturn', 'RedCard', 'PenaltyAwarded', 'PenaltyMissed')


class FollowLimits(Strict):
    min_minutes_between_narratives: float = Field(ge=0, le=90)  # per topic (pivotal key events excepted)
    # ETL key event types that bypass the gap for a topic they involve (half and full time always do).
    pivotal_key_types: list[Literal[KEY_TYPES]] = Field(max_length=len(KEY_TYPES))
    max_topics_per_match: int = Field(ge=1, le=1000)            # the engine works on the most followed first
    planner_turns_per_minute: int = Field(ge=1, le=120)         # per viewer
    follow_changes_per_minute: int = Field(ge=1, le=120)        # follows plus unfollows, per viewer
    planner_context_turns: int = Field(ge=1, le=50)             # earlier follow-chat turns the planner sees
    period_end_wrap_up: bool                                    # half and full time fire every follow (030)


class FollowCatchUp(Strict):
    """The trigger reason the engine gives the author for a viewer's "story so far" step (a description, not an
    instruction: the subscription-author prompt says what to write)."""
    reason: Text
    retries: int = Field(ge=0, le=5)  # a story so far dropped as ungrounded is tried again at later horizons


class FollowSuggestions(Strict):
    max_items: int = Field(ge=0, le=12)
    storylines: bool
    min_storyline_salience: float = Field(ge=0, le=10)
    teams: bool
    players: bool  # players named in the key moments so far


CLIP_KINDS = ('goal', 'own_goal', 'red_card', 'second_yellow', 'penalty', 'penalty_missed', 'var_overturn')


class FollowClips(Strict):
    """Moment clips in a follow's playlist (037). On a key event of `key_types` the engine asks Decision-1 this
    score question per followed topic (in the same batched call as `decision`); its nearest level at or above `min_level` with at
    least `min_confidence`, the moment's clip joins the topic's playlist. `timing` lists the key-moment kinds that
    can be clipped and the replay-timing key that cuts each one."""
    enabled: bool
    key_types: list[Literal[KEY_TYPES]] = Field(max_length=len(KEY_TYPES))
    instructions: Text
    levels: list[Text] = Field(min_length=2, max_length=10)
    min_level: int = Field(ge=1, le=9)
    min_confidence: float = Field(ge=0, le=1)
    timing: dict[Literal[CLIP_KINDS], Annotated[str, Field(pattern=r'^[a-z_]{1,40}$')]]
    max_items: int = Field(ge=1, le=50)  # newest clips kept in a playlist
    # Topic kinds whose follows are clip-on from creation (041): a key event of `key_types` that concerns the topic
    # clips without the score question. Empty: Decision-1 judges every clip.
    always_for: list[Literal['storyline', 'team', 'player', 'theme']] = Field(max_length=4)
    # Key-event clips on the shared bucket narratives (041, PLAN.md §10.2 D7): every viewer's Insights.
    shared: bool

    @model_validator(mode='after')
    def level_in_range(self):
        if self.min_level >= len(self.levels):
            raise ValueError('min_level must name one of the levels')
        return self


class Subscriptions(Strict):
    """Story-follow tunables: the engine reads `decision`, `novelty`, `prefilter`, `limits`, `catch_up` and `clips`
    from subscription-targets."""
    decision: FollowDecision
    novelty: FollowNovelty
    prefilter: dict[Literal['minute_recaps', 'key_events', 'storyline_updates'], bool]
    limits: FollowLimits
    catch_up: FollowCatchUp
    suggestions: FollowSuggestions
    # Planner entity resolution: the share of a name's words a reply must match (0.5: half of them).
    min_name_match: float = Field(gt=0, le=1)
    max_candidates: int = Field(ge=1, le=12)  # entities offered back when a name is ambiguous (031)
    clips: FollowClips  # moment clips in a follow's playlist (037)


MOMENT_KINDS = ('goal', 'own_goal', 'red_card', 'second_yellow', 'penalty', 'penalty_missed', 'var_overturn',
                'kick_off', 'half_time', 'second_half', 'full_time', 'period_start', 'period_end')


class KeyMomentFeed(Strict):
    """Pivotal key moments every viewer's feed shows: which kinds, and each one's line. Templates take
    {subject} ({player} ({team}) when the moment has a player, else {team}), {team}, {player}, {scorer} (= {player}),
    {period} and {score} (the score after the moment, from the `score` template: {home}, {away}, {home_goals},
    {away_goals})."""
    kinds: list[Literal[MOMENT_KINDS]] = Field(max_length=len(MOMENT_KINDS))
    labels: dict[Literal[MOMENT_KINDS], Text]
    subject_with_player: Text
    score: Text

    @model_validator(mode='after')
    def every_label(self):
        if set(self.labels) != set(MOMENT_KINDS):
            raise ValueError('labels needs every kind: ' + ', '.join(MOMENT_KINDS))
        return self


Share = Annotated[float, Field(ge=0, le=1)]
Count = Annotated[int, Field(ge=0, le=100)]


class AnalysisPolicy(Strict):
    """The analyst's grounding limits (narrative engine analysis/validator.py)."""
    max_observations: int = Field(ge=1, le=20)
    max_evidence: int = Field(ge=1, le=40)
    confidence_levels: dict[Annotated[str, Field(pattern=r'^[a-z]{1,20}$')], Share] = Field(min_length=1, max_length=10)
    confidence_cap_short: Share    # evidence only from short_windows
    confidence_cap_long: Share
    short_windows: list[Literal['last5', 'last15', 'half', 'match']] = Field(max_length=4)
    value_tolerance: float = Field(ge=0, le=1)       # absolute, for a cited value against the served row
    relative_tolerance: float = Field(ge=0, le=0.5)  # share of the served value
    small_counts_up_to: Count                        # numbers always allowed in text ("two spells")
    label_chars: tuple[Annotated[int, Field(ge=1, le=200)], Annotated[int, Field(ge=1, le=200)]]
    headline_max_chars: int = Field(ge=20, le=1000)
    explanation_max_chars: int = Field(ge=20, le=2000)
    outcome_max_chars: int = Field(ge=20, le=1000)

    @model_validator(mode='after')
    def ordered(self):
        if self.label_chars[0] > self.label_chars[1] or self.confidence_cap_short > self.confidence_cap_long:
            raise ValueError('label_chars must be [min, max] and the short cap at most the long cap')
        return self


class StorylinesPolicy(Strict):
    """Storyline lifecycle, salience and focus rotation (narrative engine analysis/storylines.py)."""
    max_active: int = Field(ge=1, le=20)
    dormant_after: Count     # analyses without a development
    resolve_after: Count
    quiet_fade: Share        # salience factor per quiet analysis
    beat_weight: float = Field(ge=0, le=5)
    beats_counted: Count
    key_event_boost: dict[Literal[KEY_TYPES], Annotated[float, Field(ge=0, le=5)]]
    focus_repeat_penalty: float = Field(ge=0, le=5)  # per appearance in the last focus_recent_steps steps
    focus_recent_steps: Count
    beats_shown: int = Field(ge=1, le=20)             # latest beats per storyline in prompts (031)
    resolved_shown_minutes: int = Field(ge=0, le=130)  # a resolved storyline stays in authors' prompts this long
    # Whole-match trend indicators an author always sees, flagged or not (the rest only when flagged).
    author_match_indicators: list[Annotated[str, Field(pattern=r'^[a-z_]{1,40}$')]] = Field(max_length=30)
    reopen_within: int = Field(ge=-1, le=130)  # minutes a resolved storyline of the same label reopens (-1: never) (036)


class RepairPolicy(Strict):
    analyst_turns: int = Field(ge=0, le=3)    # per analysis, for the items the validator rejected
    author_rewrites: int = Field(ge=0, le=3)  # per excerpt, before it is dropped
    author_trim: bool  # after the rewrites: remove only sentences whose claims still fail (false: drop the excerpt)


class ClaimCheck(Strict):
    """Two yes/no questions the decision model answers per sentence of an author excerpt (and, with `analyst`, of
    the analyst's observations and resolves): does it make this kind of claim, and does the evidence shown support
    it? Unsupported claims are rewritten, then dropped (narrative engine analysis/validator.claim_reasons)."""
    enabled: bool
    claim: Annotated[str, Field(min_length=1, max_length=600)]
    support: Annotated[str, Field(min_length=1, max_length=600)]
    min_claim_probability: Share
    min_support_probability: Share
    repair: Annotated[str, Field(min_length=1, max_length=300)]  # the rewrite request's reason
    analyst: bool  # also asked of the analyst's observations and resolves, against its inputs (030)


class ClaimsPolicy(Strict):
    causal: ClaimCheck
    intent: ClaimCheck
    result: ClaimCheck  # the match's result before the evidence shows it has ended (029)
    comparison: ClaimCheck  # a comparison the numbers shown do not support in that direction (030)
    score: ClaimCheck  # a score, or what a goal did to it, the ledger does not show (036)


class StorylinePolicy(Strict):
    """Served to the narrative engine at GET /storyline-policy; seeded by migrations/026 (claims: 027, 029)."""
    analysis: AnalysisPolicy
    storylines: StorylinesPolicy
    repair: RepairPolicy
    claims: ClaimsPolicy


class CrossMatch(Strict):
    """Reach into the demo's other live matches (PLAN.md §10.2, 040): a question that names another match's team or
    player is answered from that match, a stat from it can be pinned, and its storylines, teams and players can be
    followed. Its data is bounded by that match's own position, never this viewer's."""
    enabled: bool
    # A question is about another match when at least this weighted share of one of its team or player names
    # appears (rarity-weighted words across every live match), and more than for the viewer's own match.
    min_name_coverage: float = Field(gt=0, le=1)
    suggest_teams: bool  # follow suggestions also offer the other matches' teams


class FollowOffer(Strict):
    """The "Follow this story?" offer on a question's answer (PLAN.md §10.2 D5b, 040): for an answered question
    that is not a statistic, Decision-1 answers this yes/no question; at or above `min_probability` the answer card
    offers to set up a follow from the question. Offers are optional: none when the decision is unavailable,
    slow or over `max_per_minute` (requests from this service; the deployment's limit is shared with the engine)."""
    enabled: bool
    instructions: Text
    true: Text
    false: Text
    min_probability: float = Field(ge=0, le=1)
    max_per_minute: int = Field(ge=0, le=600)
    timeout_seconds: float = Field(gt=0, le=30)


class RoleModel(Strict):
    """One role's model. An empty deployment keeps the service's own setting (Terraform/env); a set one is a
    deployment on the same model endpoint. An effort sends the call as a reasoning model (Responses API for the
    backend's tool-using agents); none sends it as a chat model with temperature 0."""
    deployment: str = Field(default='', max_length=64, pattern=r'^[A-Za-z0-9._-]*$')
    effort: Literal['', 'minimal', 'low', 'medium', 'high'] = ''


class EngineModels(Strict):
    summary: RoleModel
    compression: RoleModel
    analyst: RoleModel
    author: RoleModel  # shared bucket insights and followed-story narratives


class BackendModels(Strict):
    questions: RoleModel  # the Ask chat: question, goal and intent agents
    follow_planner: RoleModel
    replay: RoleModel


class ModelRoles(Strict):
    """Model per role, switched live (PLAN.md §12 M10, 047): the backend applies `backend` within seconds; the
    engine reads `engine` at GET /model-roles. `deployments` lists what the model endpoint offers, for the editor."""
    deployments: list[str] = Field(max_length=20)
    engine: EngineModels
    backend: BackendModels


CONFIGS = {'presentation': Presentation, 'replay-timing': Replay, 'key-moment-ranks': KeyMoments,
           'prices': Prices, 'stream': Stream, 'subscriptions': Subscriptions, 'key-moment-feed': KeyMomentFeed,
           'storyline-policy': StorylinePolicy, 'cross-match': CrossMatch, 'follow-offer': FollowOffer,
           'models': ModelRoles}
ConfigName = Literal['presentation', 'replay-timing', 'key-moment-ranks', 'prices', 'stream', 'subscriptions',
                     'key-moment-feed', 'storyline-policy', 'cross-match', 'follow-offer', 'models']
