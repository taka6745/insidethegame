-- Stat catalogue on SPADL (local/README.md Contracts §4): 42 kinds × 3 scopes. Replaces 004's canonical-event
-- definitions; kinds keep their ids where the concept is the same (the old → new mapping and every value
-- change are in local/README.md Contracts §4). statsAtSeq(@matchId, @seq) (009_spadl_stats_staged.sql) counts
-- dbo.spadlActions with finalSeq <= @seq; cards and VAR overturns come from MA3 rows and possession from POS
-- samples, outside SPADL. reference/catalogue.py reads the seed below and is the executable expectation.
--
-- counter (actions of actionTypes, optionally with resultName = result and bodypartName = bodypart):
--   count           the team's matching actions
--   opponent_count  the opponent's matching actions (fouls won); both teams: all of them
--   goals           the team's successful actionTypes plus the opponent's own goals (result owngoal), less
--                   VAR overturns (MA3 type 900, qualifier 901 goal-overturned, eventSeq <= @seq) of the
--                   row's team, or of the opponent for an overturned own goal (qualifier 28)
--   on_target       result success, or an attempt saved (sourceTypeId 15) ending on the goal line
--   blocked         an attempt saved (sourceTypeId 15) ending before the goal line
--   keeper_saves    matching actions with fromShotOffTarget and defensiveBlock both false (real saves)
--   accuracy        successful / all matching actions (%); unavailable without any
--   entries         matching actions from a zone below `zone` to `zone` or beyond (zones in order own_box,
--                   defensive_third, middle_third, final_third, opp_box, relative to the acting team)
--   cards           MA3 card rows (Opta type 17) with eventSeq <= @seq
--   possession      share of POS ownership seconds up to the snapshot's video time (%)
--   retired         no SPADL definition: always available = 0, value null
-- requires (all must hold, else available = 0 and value null): shotOutcomes (MA1 capabilities.shotOutcomes
--   is not false); bodyParts (capabilities.bodyParts, or every one of actionTypes in the SPADL
--   capabilities.bodyPartActionTypes).

DROP TABLE dbo.statDefinitions;
GO

CREATE TABLE dbo.statDefinitions (
    statId        nvarchar(40)  NOT NULL CONSTRAINT PK_statDefinitions PRIMARY KEY,  -- the kind, e.g. goals
    label         nvarchar(80)  NOT NULL,
    unit          nvarchar(8)   NOT NULL,
    definition    nvarchar(400) NOT NULL,
    actionTypes   nvarchar(400) NOT NULL CONSTRAINT CK_statDefinitions_actionTypes CHECK (ISJSON(actionTypes) = 1),
    result        nvarchar(16)  NULL,
    bodypart      nvarchar(16)  NULL,
    zone          nvarchar(16)  NULL CONSTRAINT CK_statDefinitions_zone CHECK (zone IN
                  ('own_box', 'defensive_third', 'middle_third', 'final_third', 'opp_box')),
    counter       nvarchar(32)  NOT NULL CONSTRAINT CK_statDefinitions_counter CHECK (counter IN
                  ('count', 'opponent_count', 'goals', 'on_target', 'blocked', 'keeper_saves', 'accuracy',
                   'entries', 'cards', 'possession', 'retired')),
    requires      nvarchar(400) NOT NULL CONSTRAINT CK_statDefinitions_requires CHECK (ISJSON(requires) = 1),
    displayOrder  int           NOT NULL,
    enabled       bit           NOT NULL CONSTRAINT DF_statDefinitions_enabled DEFAULT 1
);
GO

DECLARE @definitions nvarchar(max) = N'[
{"statId": "goals", "label": "goals", "unit": "", "definition": "Successful SPADL shots (shot, shot_freekick, shot_penalty) plus the opponent''s own goals (result owngoal), less goals overturned by VAR.", "actionTypes": ["shot", "shot_freekick", "shot_penalty"], "result": null, "bodypart": null, "zone": null, "counter": "goals", "requires": []},
{"statId": "shots", "label": "shots", "unit": "", "definition": "SPADL shot, shot_freekick and shot_penalty actions; own goals are bad_touch, not shots.", "actionTypes": ["shot", "shot_freekick", "shot_penalty"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "passes", "label": "passes", "unit": "", "definition": "SPADL pass-family actions: pass, cross, throw_in, freekick_crossed, freekick_short, corner_crossed, corner_short, goalkick.", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "corners", "label": "corners", "unit": "", "definition": "Corners taken: SPADL corner_crossed and corner_short.", "actionTypes": ["corner_crossed", "corner_short"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "cards", "label": "cards", "unit": "", "definition": "Cards shown (yellow, second yellow, red): MA3 card events (Opta type 17), outside SPADL.", "actionTypes": [], "result": null, "bodypart": null, "zone": null, "counter": "cards", "requires": []},
{"statId": "tackles", "label": "tackles", "unit": "", "definition": "SPADL tackle actions.", "actionTypes": ["tackle"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "interceptions", "label": "interceptions", "unit": "", "definition": "SPADL interception actions, including blocked passes.", "actionTypes": ["interception"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "fouls", "label": "fouls", "unit": "", "definition": "Fouls committed: SPADL foul actions.", "actionTypes": ["foul"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "fouls_won", "label": "fouls won", "unit": "", "definition": "Fouls committed by the opponent (SPADL foul); both teams: every foul.", "actionTypes": ["foul"], "result": null, "bodypart": null, "zone": null, "counter": "opponent_count", "requires": []},
{"statId": "offsides", "label": "offsides", "unit": "", "definition": "SPADL pass-family actions with result offside.", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"], "result": "offside", "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "throw_ins", "label": "throw ins", "unit": "", "definition": "SPADL throw_in actions.", "actionTypes": ["throw_in"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "free_kicks", "label": "free kicks", "unit": "", "definition": "Free kicks taken: SPADL freekick_crossed, freekick_short and shot_freekick.", "actionTypes": ["freekick_crossed", "freekick_short", "shot_freekick"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "goal_kicks", "label": "goal kicks", "unit": "", "definition": "SPADL goalkick actions.", "actionTypes": ["goalkick"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "kick_offs", "label": "kick offs", "unit": "", "definition": "Retired: SPADL has no kick-off action (a kick-off is a pass).", "actionTypes": [], "result": null, "bodypart": null, "zone": null, "counter": "retired", "requires": []},
{"statId": "penalties", "label": "penalties", "unit": "", "definition": "Penalty kicks taken: SPADL shot_penalty.", "actionTypes": ["shot_penalty"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "keeper_claims", "label": "keeper claims", "unit": "", "definition": "SPADL keeper_claim actions.", "actionTypes": ["keeper_claim"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "clearances", "label": "clearances", "unit": "", "definition": "SPADL clearance actions.", "actionTypes": ["clearance"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "take_ons", "label": "take ons", "unit": "", "definition": "SPADL take_on actions.", "actionTypes": ["take_on"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "ball_recoveries", "label": "ball recoveries", "unit": "", "definition": "Retired: SPADL turns a ball recovery into a dribble (see dribbles) or drops it.", "actionTypes": [], "result": null, "bodypart": null, "zone": null, "counter": "retired", "requires": []},
{"statId": "headed_passes", "label": "headed passes", "unit": "", "definition": "SPADL pass-family actions with bodypart head; needs body parts for passes.", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"], "result": null, "bodypart": "head", "zone": null, "counter": "count", "requires": ["bodyParts"]},
{"statId": "headed_shots", "label": "headed shots", "unit": "", "definition": "SPADL shots with bodypart head; needs body parts for shots.", "actionTypes": ["shot", "shot_freekick", "shot_penalty"], "result": null, "bodypart": "head", "zone": null, "counter": "count", "requires": ["bodyParts"]},
{"statId": "headed_contacts", "label": "headed contacts", "unit": "", "definition": "SPADL actions of any type with bodypart head; needs body parts for every action.", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "take_on", "foul", "tackle", "interception", "shot", "shot_penalty", "shot_freekick", "keeper_save", "keeper_claim", "keeper_punch", "keeper_pick_up", "clearance", "bad_touch", "dribble", "goalkick"], "result": null, "bodypart": "head", "zone": null, "counter": "count", "requires": ["bodyParts"]},
{"statId": "saves", "label": "saves", "unit": "", "definition": "SPADL keeper_save actions (Opta save events, including blocks).", "actionTypes": ["keeper_save"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "shots_on_target", "label": "shots on target", "unit": "", "definition": "Goals plus attempts saved (Opta 15) whose end reached the goal line.", "actionTypes": ["shot", "shot_freekick", "shot_penalty"], "result": null, "bodypart": null, "zone": null, "counter": "on_target", "requires": ["shotOutcomes"]},
{"statId": "blocked_shots", "label": "blocked shots", "unit": "", "definition": "Attempts saved (Opta 15) stopped before the goal line.", "actionTypes": ["shot", "shot_freekick", "shot_penalty"], "result": null, "bodypart": null, "zone": null, "counter": "blocked", "requires": ["shotOutcomes"]},
{"statId": "aerials_won", "label": "aerials won", "unit": "", "definition": "Retired: SPADL has no aerial duel action.", "actionTypes": [], "result": null, "bodypart": null, "zone": null, "counter": "retired", "requires": []},
{"statId": "successful_take_ons", "label": "successful take ons", "unit": "", "definition": "SPADL take_on actions with result success.", "actionTypes": ["take_on"], "result": "success", "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "pass_accuracy", "label": "pass accuracy", "unit": "%", "definition": "Successful / all SPADL pass-family actions (%); offside counts as unsuccessful.", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"], "result": null, "bodypart": null, "zone": null, "counter": "accuracy", "requires": []},
{"statId": "possession", "label": "possession", "unit": "%", "definition": "Share of measured native simulation ball-ownership seconds; unowned ball excluded.", "actionTypes": [], "result": null, "bodypart": null, "zone": null, "counter": "possession", "requires": []},
{"statId": "passes_completed", "label": "passes completed", "unit": "", "definition": "SPADL pass-family actions with result success.", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"], "result": "success", "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "crosses", "label": "crosses", "unit": "", "definition": "SPADL cross, corner_crossed and freekick_crossed actions.", "actionTypes": ["cross", "corner_crossed", "freekick_crossed"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "crosses_completed", "label": "crosses completed", "unit": "", "definition": "SPADL cross, corner_crossed and freekick_crossed actions with result success.", "actionTypes": ["cross", "corner_crossed", "freekick_crossed"], "result": "success", "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "cross_accuracy", "label": "cross accuracy", "unit": "%", "definition": "Successful / all SPADL crosses (cross, corner_crossed, freekick_crossed) (%).", "actionTypes": ["cross", "corner_crossed", "freekick_crossed"], "result": null, "bodypart": null, "zone": null, "counter": "accuracy", "requires": []},
{"statId": "dribbles", "label": "dribbles", "unit": "", "definition": "SPADL dribble actions (carries): the ball moved 3-60 m by one team between two actions, or after a recovery.", "actionTypes": ["dribble"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "corners_crossed", "label": "corners crossed", "unit": "", "definition": "SPADL corner_crossed actions.", "actionTypes": ["corner_crossed"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "corners_short", "label": "corners short", "unit": "", "definition": "SPADL corner_short actions.", "actionTypes": ["corner_short"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "free_kicks_crossed", "label": "free kicks crossed", "unit": "", "definition": "SPADL freekick_crossed actions.", "actionTypes": ["freekick_crossed"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "free_kicks_short", "label": "free kicks short", "unit": "", "definition": "SPADL freekick_short actions.", "actionTypes": ["freekick_short"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "free_kick_shots", "label": "free kick shots", "unit": "", "definition": "SPADL shot_freekick actions.", "actionTypes": ["shot_freekick"], "result": null, "bodypart": null, "zone": null, "counter": "count", "requires": []},
{"statId": "final_third_entries", "label": "final third entries", "unit": "", "definition": "Successful SPADL passes and dribbles from outside the final third into it (team-relative zones).", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick", "dribble"], "result": "success", "bodypart": null, "zone": "final_third", "counter": "entries", "requires": []},
{"statId": "box_entries", "label": "box entries", "unit": "", "definition": "Successful SPADL passes and dribbles from outside the opponent''s penalty area into it.", "actionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick", "dribble"], "result": "success", "bodypart": null, "zone": "opp_box", "counter": "entries", "requires": []},
{"statId": "shots_saved", "label": "shots saved", "unit": "", "definition": "Goalkeeper saves: SPADL keeper_save actions that are neither a touch of a shot going wide (fromShotOffTarget) nor an outfield block (defensiveBlock).", "actionTypes": ["keeper_save"], "result": null, "bodypart": null, "zone": null, "counter": "keeper_saves", "requires": []}
]';
INSERT dbo.statDefinitions (statId, label, unit, definition, actionTypes, result, bodypart, zone, counter, requires,
                            displayOrder)
SELECT d.statId, d.label, d.unit, d.definition, d.actionTypes, d.result, d.bodypart, d.zone, d.counter, d.requires,
       CAST(d.[key] AS int) + 1
FROM (SELECT j.[key], v.*
      FROM OPENJSON(@definitions) AS j
      CROSS APPLY OPENJSON(j.value) WITH (
          statId nvarchar(40), label nvarchar(80), unit nvarchar(8), definition nvarchar(400),
          actionTypes nvarchar(max) AS JSON, result nvarchar(16), bodypart nvarchar(16), zone nvarchar(16),
          counter nvarchar(32), requires nvarchar(max) AS JSON) AS v) AS d;
GO
