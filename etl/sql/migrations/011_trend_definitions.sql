-- Trend definitions (local/contracts/README.md §4b): configuration for trendsAtSeq, trendSpellsAtSeq and
-- trendMinutesAtSeq (012_trends_at_seq.sql). Formulas are fixed in the procedures (and reference/trends.py);
-- this table holds what is tunable: whether a trend may be claimed (enabled) and its thresholds.
--
-- family     indicator, composite (built from indicators), momentum (per-minute series), spell (runs of minutes)
-- notableAt  level flag "notable" at or above (calibrated: pooled last-5 p80 on the GRF recordings)
-- highAt     level flag "high" at or above (last-5 p90); a high level is a claim (flagged)
-- changeAt   change flag "rising"/"falling" when |value − baseline| is at or above (|Δ vs prev10| p90); null: none
-- minuteAt, minMinutes, minBallSeconds  spells: a minute counts when the zone share is at or above minuteAt with
--            at least minBallSeconds of ball time; a spell is at least minMinutes long
-- enabled    0: served with no flags (values stay usable as decoration), never a claim
--
-- Re-seeding: dbo.seedTrendDefinitions replaces every row with one JSON block (rows missing from the block are
-- deleted; displayOrder follows the block). To re-seed after this migration has been applied anywhere, add a
-- migration that declares the whole block as @trendDefinitions (as below) and passes it to
-- dbo.seedTrendDefinitions. reference/trends.py reads the newest such block.

CREATE TABLE dbo.trendDefinitions (
    trendId         nvarchar(40)  NOT NULL CONSTRAINT PK_trendDefinitions PRIMARY KEY,
    family          nvarchar(16)  NOT NULL CONSTRAINT CK_trendDefinitions_family CHECK (family IN
                    ('indicator', 'composite', 'momentum', 'spell')),
    label           nvarchar(80)  NOT NULL,
    unit            nvarchar(16)  NOT NULL,
    definition      nvarchar(600) NOT NULL,
    enabled         bit           NOT NULL,
    notableAt       float         NULL,
    highAt          float         NULL,
    changeAt        float         NULL,
    minuteAt        float         NULL,
    minMinutes      int           NULL,
    minBallSeconds  float         NULL,
    evidence        nvarchar(300) NOT NULL,  -- why it is enabled or not
    displayOrder    int           NOT NULL
);
GO

CREATE OR ALTER PROCEDURE dbo.seedTrendDefinitions @definitions nvarchar(max)
AS
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;
MERGE dbo.trendDefinitions AS t
USING (SELECT v.*, CAST(j.[key] AS int) + 1 AS displayOrder
       FROM OPENJSON(@definitions) AS j
       CROSS APPLY OPENJSON(j.value) WITH (
           trendId nvarchar(40), family nvarchar(16), label nvarchar(80), unit nvarchar(16),
           definition nvarchar(600), enabled bit, notableAt float, highAt float, changeAt float, minuteAt float,
           minMinutes int, minBallSeconds float, evidence nvarchar(300)) AS v) AS s
ON t.trendId = s.trendId
WHEN MATCHED THEN UPDATE SET family = s.family, label = s.label, unit = s.unit, definition = s.definition,
    enabled = s.enabled, notableAt = s.notableAt, highAt = s.highAt, changeAt = s.changeAt, minuteAt = s.minuteAt,
    minMinutes = s.minMinutes, minBallSeconds = s.minBallSeconds, evidence = s.evidence, displayOrder = s.displayOrder
WHEN NOT MATCHED BY TARGET THEN INSERT (trendId, family, label, unit, definition, enabled, notableAt, highAt, changeAt,
    minuteAt, minMinutes, minBallSeconds, evidence, displayOrder)
    VALUES (s.trendId, s.family, s.label, s.unit, s.definition, s.enabled, s.notableAt, s.highAt, s.changeAt,
            s.minuteAt, s.minMinutes, s.minBallSeconds, s.evidence, s.displayOrder)
WHEN NOT MATCHED BY SOURCE THEN DELETE;
COMMIT;
GO

-- Seed: the decision table. One block; edit it as a whole.
DECLARE @trendDefinitions nvarchar(max) = N'[
{"trendId": "possession", "family": "indicator", "label": "possession", "unit": "share", "enabled": true, "notableAt": 0.60, "highAt": 0.66, "changeAt": 0.21, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Separates teams: eta2 0.16, p 0.005.", "definition": "Share of measured ball-ownership seconds (POS samples, each in the minute it ends in), (own + 1) / (own + opponent + 2)."},
{"trendId": "field_tilt", "family": "indicator", "label": "field tilt", "unit": "share", "enabled": true, "notableAt": 0.70, "highAt": 0.77, "changeAt": 0.35, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Separates teams: eta2 0.31, p 0.005.", "definition": "Share of on-ball SPADL actions (fouls excluded) starting in the final third (team frame, x >= 70 m), (own + 1) / (own + opponent + 2)."},
{"trendId": "att_half_share", "family": "indicator", "label": "attacking-half share", "unit": "share", "enabled": true, "notableAt": 0.62, "highAt": 0.68, "changeAt": 0.22, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Separates teams: eta2 0.28, p 0.005.", "definition": "Share of ball time in the team''s attacking half: each SPADL action''s start holds until the next action (at most 8 s; 1 s after a period''s last), (seconds + 1) / (ball seconds + 2)."},
{"trendId": "final_third_share", "family": "indicator", "label": "final-third share", "unit": "share", "enabled": true, "notableAt": 0.47, "highAt": 0.53, "changeAt": 0.21, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Separates teams: eta2 0.30, p 0.005.", "definition": "Share of ball time (as attacking-half share) in the team''s final third (x >= 70 m), (seconds + 1) / (ball seconds + 2)."},
{"trendId": "def_height", "family": "indicator", "label": "defensive action height", "unit": "m", "enabled": true, "notableAt": 52.4, "highAt": 58.0, "changeAt": 18.0, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Separates teams: eta2 0.25, p 0.005.", "definition": "Mean distance from the own goal line (m) of MA3 tackles, interceptions, challenges, fouls committed, clearances, ball recoveries and blocked passes; null without any."},
{"trendId": "box_entries", "family": "indicator", "label": "box entries", "unit": "per 5 min", "enabled": true, "notableAt": 5.8, "highAt": 7.0, "changeAt": 3.5, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Separates teams: eta2 0.16, p 0.005.", "definition": "Successful SPADL passes and dribbles from outside into the opponent''s penalty area, the first per possession, per 5 minutes."},
{"trendId": "dominance", "family": "composite", "label": "dominance", "unit": "index", "enabled": true, "notableAt": 0.21, "highAt": 0.30, "changeAt": 0.40, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Separates teams: eta2 0.24, p 0.005; does not track the score (r +0.03): a half or match lead line.", "definition": "2 x (mean of possession, field tilt, attacking-half share, shot share and final-third entry share - 0.5), from -1 to 1; shot and entry shares carry the +1 prior."},
{"trendId": "shots", "family": "indicator", "label": "shots", "unit": "per 5 min", "enabled": true, "notableAt": 1, "highAt": 2, "changeAt": null, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "A count, not a trend: not team-distinct (p 0.6) and too sparse.", "definition": "SPADL shot, shot_freekick and shot_penalty actions per 5 minutes."},
{"trendId": "box_shots", "family": "indicator", "label": "shots in the box", "unit": "per 5 min", "enabled": true, "notableAt": 1, "highAt": 2, "changeAt": null, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "A count, not a trend (p 0.59).", "definition": "Shots starting in the opponent''s penalty area per 5 minutes."},
{"trendId": "ft_entries", "family": "indicator", "label": "final-third entries", "unit": "per 5 min", "enabled": true, "notableAt": 5, "highAt": 6, "changeAt": null, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "A count, not a trend (p 0.21).", "definition": "Successful SPADL passes and dribbles from below the final third into it (x crosses 70 m), the first per possession, per 5 minutes."},
{"trendId": "fouls", "family": "indicator", "label": "fouls", "unit": "per 5 min", "enabled": true, "notableAt": 1, "highAt": 2, "changeAt": null, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "A count: eta2 0.13, p 0.03.", "definition": "Fouls committed (MA3 type 4, outcome 0) per 5 minutes."},
{"trendId": "cards", "family": "indicator", "label": "cards", "unit": "per 5 min", "enabled": true, "notableAt": null, "highAt": null, "changeAt": null, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "A count; any card is a key event of its own.", "definition": "Cards shown (MA3 type 17) per 5 minutes."},
{"trendId": "ppda", "family": "indicator", "label": "passes per defensive action", "unit": "ratio", "enabled": false, "notableAt": 15, "highAt": 18.9, "changeAt": 19.46, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Disabled: about 22 pressing actions per team per match, so a short window is mostly the prior; p 0.26.", "definition": "Opponent passes (MA3 type 1) in their own 60% + 1, over own tackles, interceptions, challenges and fouls in the attacking 60% + 1; lower means more pressing."},
{"trendId": "contests", "family": "indicator", "label": "contests", "unit": "per 5 min", "enabled": false, "notableAt": 7, "highAt": 8.9, "changeAt": 4.5, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Disabled: eta2 0.01, p 0.98.", "definition": "MA3 tackles, challenges, aerial duels and take-ons per 5 minutes."},
{"trendId": "aggression", "family": "composite", "label": "aggression", "unit": "per 5 min", "enabled": false, "notableAt": 2.5, "highAt": 4.0, "changeAt": 3.0, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Disabled (use fouls and cards): p 0.14.", "definition": "(fouls + 3 x cards + 0.5 x (tackles + challenges)) per 5 minutes, from MA3."},
{"trendId": "fast_breaks", "family": "indicator", "label": "fast breaks", "unit": "per 5 min", "enabled": false, "notableAt": 3, "highAt": 4, "changeAt": 3.0, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Disabled: about 40 per team per match, so it measures end-to-end play, not counters; p 0.57.", "definition": "Open-play possessions starting in the own half that reach the final third with at least 30 m of progress, or shoot, within 12 s, per 5 minutes (counted in their first action''s minute)."},
{"trendId": "directness", "family": "indicator", "label": "directness", "unit": "share", "enabled": false, "notableAt": 0.57, "highAt": 0.60, "changeAt": 0.16, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Phase 2 (eta2 0.09, p 0.10); stall nudges change it by at most 0.002 a match.", "definition": "Forward metres over total metres of open-play passes and crosses (SPADL pass and cross), (forward + 1) / (total + 2)."},
{"trendId": "long_ball_share", "family": "indicator", "label": "long-ball share", "unit": "share", "enabled": false, "notableAt": 0.07, "highAt": 0.08, "changeAt": 0.05, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Phase 2 (eta2 0.10, p 0.03).", "definition": "Share of open-play passes and crosses of at least 32 m, (long + 1) / (passes + 2)."},
{"trendId": "momentum", "family": "momentum", "label": "momentum", "unit": "threat", "enabled": false, "notableAt": 2.96, "highAt": 3.81, "changeAt": null, "minuteAt": null, "minMinutes": null, "minBallSeconds": null, "evidence": "Disabled as a claim (the curve is fine as decoration): max |momentum| pooled p 0.25, 5-minute swing p 0.26.", "definition": "Per minute, exponentially weighted (alpha 0.4, from kick-off) team-minus-opponent threat; threat = 0.02 x final-third seconds + final-third entries + 2 x box entries + 3 x shots."},
{"trendId": "territory_spell", "family": "spell", "label": "territory spell", "unit": "minutes", "enabled": false, "notableAt": null, "highAt": null, "changeAt": null, "minuteAt": 0.75, "minMinutes": 3, "minBallSeconds": 15, "evidence": "Disabled: real spells are no longer than shuffled minutes (pooled p 0.85).", "definition": "A run of minutes within a period with attacking-half share at or above minuteAt (and at least minBallSeconds of ball time), bridging single minutes below it."},
{"trendId": "pressure_spell", "family": "spell", "label": "pressure spell", "unit": "minutes", "enabled": false, "notableAt": null, "highAt": null, "changeAt": null, "minuteAt": 0.58, "minMinutes": 3, "minBallSeconds": 15, "evidence": "Disabled: pooled p 0.998 against shuffled minutes.", "definition": "As a territory spell, on final-third share, and each counted minute has a final-third entry, a box entry or a shot."}
]';
EXEC dbo.seedTrendDefinitions @trendDefinitions;
GO
