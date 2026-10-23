-- Trend parameters: the constants inside the trend formulas become configuration, beside
-- trendDefinitions. dbo.trendMinuteRows (014) is recreated to read them; the seed holds the values 014 had
-- inline, so every served value is unchanged. Changing a value changes what the trends measure (the definitions'
-- text names them): recalibrate the thresholds (python -m devtools.calibrate_trends) after any change.
--
-- Re-seeding: dbo.seedTrendParameters replaces every row with one JSON block, like dbo.seedTrendDefinitions;
-- reference/trends.py reads the newest @trendParameters block.

CREATE TABLE dbo.trendParameters (
    name    nvarchar(40)  NOT NULL CONSTRAINT PK_trendParameters PRIMARY KEY,
    value   float         NOT NULL,
    meaning nvarchar(300) NOT NULL
);
GO

CREATE OR ALTER PROCEDURE dbo.seedTrendParameters @parameters nvarchar(max)
AS
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;
MERGE dbo.trendParameters AS t
USING (SELECT v.* FROM OPENJSON(@parameters) WITH (name nvarchar(40), value float, meaning nvarchar(300)) AS v) AS s
ON t.name = s.name
WHEN MATCHED THEN UPDATE SET value = s.value, meaning = s.meaning
WHEN NOT MATCHED BY TARGET THEN INSERT (name, value, meaning) VALUES (s.name, s.value, s.meaning)
WHEN NOT MATCHED BY SOURCE THEN DELETE;
COMMIT;
GO

DECLARE @trendParameters nvarchar(max) = N'[
{"name": "ball_gap_cap_seconds", "value": 8, "meaning": "An action''s start holds the ball until the next action, at most this many seconds."},
{"name": "ball_last_gap_seconds", "value": 1, "meaning": "Seconds the last action of a period holds the ball."},
{"name": "long_pass_metres", "value": 32, "meaning": "A pass or cross at least this long is a long ball."},
{"name": "fast_break_seconds", "value": 12, "meaning": "A fast break reaches its target before any action this many seconds after its first."},
{"name": "fast_break_metres", "value": 30, "meaning": "Progress a fast break makes when it reaches the final third."},
{"name": "momentum_alpha", "value": 0.4, "meaning": "Weight of the latest minute in the momentum average (EWMA)."},
{"name": "build_line_metres", "value": 63, "meaning": "Opponent passes below this x (their own 60%) are build-up passes, for ppda."},
{"name": "press_line_metres", "value": 42, "meaning": "Defensive actions at or above this x (the attacking 60%) are pressing actions, for ppda."},
{"name": "flank_lanes", "value": 3, "meaning": "The width splits into this many lanes; the outer two are the right and left flanks."},
{"name": "threat_final_third_second", "value": 0.02, "meaning": "Threat per second of ball time in the final third."},
{"name": "threat_final_third_entry", "value": 1, "meaning": "Threat per final-third entry."},
{"name": "threat_box_entry", "value": 2, "meaning": "Threat per box entry."},
{"name": "threat_shot", "value": 3, "meaning": "Threat per shot."}
]';
EXEC dbo.seedTrendParameters @parameters = @trendParameters;
GO

-- dbo.trendMinuteRows as 014, reading the parameters above.
CREATE OR ALTER FUNCTION dbo.trendMinuteRows (@matchId nvarchar(64), @seq int)
RETURNS @rows TABLE (
    rn int NOT NULL, periodId int NOT NULL, minute int NOT NULL, minuteLabel nvarchar(12) NOT NULL,
    isHome bit NOT NULL, contestantId nvarchar(64) NOT NULL,
    possessionSeconds float NOT NULL, ballSeconds float NOT NULL, attHalfSeconds float NOT NULL,
    finalThirdSeconds float NOT NULL, attHalfShare float NOT NULL, finalThirdShare float NOT NULL,
    ftActions int NOT NULL, ftEntries int NOT NULL, boxEntries int NOT NULL, shots int NOT NULL, boxShots int NOT NULL,
    buildPasses int NOT NULL, pressActions int NOT NULL, defActions int NOT NULL, defMetres float NOT NULL,
    defHeight float NULL, fouls int NOT NULL, cards int NOT NULL, tackles int NOT NULL, challenges int NOT NULL,
    aerials int NOT NULL, takeOns int NOT NULL, fastBreaks int NOT NULL, passes int NOT NULL,
    forwardMetres float NOT NULL, passMetres float NOT NULL, longPasses int NOT NULL, threat float NOT NULL,
    momentum float NULL, territoryMinute bit NOT NULL, pressureMinute bit NOT NULL,
    attActions int NOT NULL, rightActions int NOT NULL, leftActions int NOT NULL, goalsFor int NOT NULL,
    leadAtStart int NOT NULL,
    PRIMARY KEY (rn, isHome))
AS
BEGIN
    DECLARE @home nvarchar(64), @away nvarchar(64), @video float, @i int = 1, @n int, @m float = 0,
            @terrAt float, @terrBall float, @pressAt float, @pressBall float,
            @gapCap float, @lastGap float, @longPass float, @breakSeconds float, @breakMetres float, @alpha float,
            @buildLine float, @pressLine float, @lanes float, @wFinal float, @wEntry float, @wBox float, @wShot float;
    SELECT @home = m.homeContestantId, @away = m.awayContestantId
    FROM dbo.matches AS m
    LEFT JOIN dbo.matchProgress AS p ON p.matchId = m.matchId
    LEFT JOIN dbo.spadlProgress AS sp ON sp.matchId = m.matchId
    WHERE m.matchId = @matchId AND @seq >= 0 AND @seq <= ISNULL(p.seq, 0) AND @seq <= ISNULL(sp.seq, 0);
    IF @home IS NULL RETURN;
    SELECT @gapCap = MAX(IIF(name = 'ball_gap_cap_seconds', value, NULL)),
           @lastGap = MAX(IIF(name = 'ball_last_gap_seconds', value, NULL)),
           @longPass = MAX(IIF(name = 'long_pass_metres', value, NULL)),
           @breakSeconds = MAX(IIF(name = 'fast_break_seconds', value, NULL)),
           @breakMetres = MAX(IIF(name = 'fast_break_metres', value, NULL)),
           @alpha = MAX(IIF(name = 'momentum_alpha', value, NULL)),
           @buildLine = MAX(IIF(name = 'build_line_metres', value, NULL)),
           @pressLine = MAX(IIF(name = 'press_line_metres', value, NULL)),
           @lanes = MAX(IIF(name = 'flank_lanes', value, NULL)),
           @wFinal = MAX(IIF(name = 'threat_final_third_second', value, NULL)),
           @wEntry = MAX(IIF(name = 'threat_final_third_entry', value, NULL)),
           @wBox = MAX(IIF(name = 'threat_box_entry', value, NULL)),
           @wShot = MAX(IIF(name = 'threat_shot', value, NULL))
    FROM dbo.trendParameters;

    DECLARE @minutes TABLE (periodId int NOT NULL, minute int NOT NULL, startVideo float NULL, PRIMARY KEY (periodId, minute));
    DECLARE @starts TABLE (periodId int NOT NULL, minute int NOT NULL, lo float NOT NULL, hi float NOT NULL, PRIMARY KEY (lo));
    -- Final actions in the team frame, with what the window functions give once: the next action's time in the
    -- same period, the first action of the possession chain (period, possession, team) and first entries.
    DECLARE @a TABLE (actionId int PRIMARY KEY, periodId int NOT NULL, timeSeconds float NOT NULL,
                      clockSeconds float NOT NULL, minute int NOT NULL, isHome bit NOT NULL, typeName nvarchar(20) NOT NULL,
                      success bit NOT NULL, hx float NOT NULL, sx float NOT NULL, sy float NOT NULL, ex float NOT NULL,
                      ey float NOT NULL, nextTime float NULL, firstAction int NULL, ftEntry bit NOT NULL, boxEntry bit NOT NULL,
                      ownGoal bit NOT NULL);
    DECLARE @g TABLE (firstAction int NOT NULL, actionId int NOT NULL, late bit NOT NULL, hit bit NOT NULL,
                      PRIMARY KEY (firstAction, actionId));
    -- Components: one row per source and (minute, team); summed below.
    DECLARE @c TABLE (periodId int NOT NULL, minute int NOT NULL, isHome bit NOT NULL, possessionSeconds float NOT NULL,
                      ballSeconds float NOT NULL, attHalfSeconds float NOT NULL, finalThirdSeconds float NOT NULL,
                      ftActions int NOT NULL, ftEntries int NOT NULL, boxEntries int NOT NULL, shots int NOT NULL,
                      boxShots int NOT NULL, buildPasses int NOT NULL, pressActions int NOT NULL, defActions int NOT NULL,
                      defMetres float NOT NULL, fouls int NOT NULL, cards int NOT NULL, tackles int NOT NULL,
                      challenges int NOT NULL, aerials int NOT NULL, takeOns int NOT NULL, fastBreaks int NOT NULL,
                      passes int NOT NULL, forwardMetres float NOT NULL, passMetres float NOT NULL, longPasses int NOT NULL,
                      attActions int NOT NULL, rightActions int NOT NULL, leftActions int NOT NULL, goalsFor int NOT NULL);

    INSERT @minutes
    SELECT e.periodId, e.matchTimeSeconds / 60, MIN(e.videoSeconds)
    FROM dbo.canonicalEvents AS e
    WHERE e.matchId = @matchId AND e.seq <= @seq
    GROUP BY e.periodId, e.matchTimeSeconds / 60;
    SELECT @video = MAX(e.videoSeconds) FROM dbo.canonicalEvents AS e WHERE e.matchId = @matchId AND e.seq <= @seq;

    -- Possession: a sample counts in the minute with the latest start at or before it (else the first minute).
    INSERT @starts
    SELECT periodId, minute, IIF(k = 1, -1e308, startVideo), ISNULL(nextVideo, 1e308)
    FROM (SELECT periodId, minute, startVideo, ROW_NUMBER() OVER (ORDER BY startVideo) AS k,
                 LEAD(startVideo) OVER (ORDER BY startVideo) AS nextVideo
          FROM @minutes WHERE startVideo IS NOT NULL) AS s;
    INSERT @c (periodId, minute, isHome, possessionSeconds, ballSeconds, attHalfSeconds, finalThirdSeconds, ftActions,
               ftEntries, boxEntries, shots, boxShots, buildPasses, pressActions, defActions, defMetres, fouls, cards,
               tackles, challenges, aerials, takeOns, fastBreaks, passes, forwardMetres, passMetres, longPasses,
               attActions, rightActions, leftActions, goalsFor)
    SELECT s.periodId, s.minute, IIF(p.contestantId = @home, 1, 0), SUM(p.durationSeconds),
           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    FROM dbo.possessionSamples AS p
    JOIN @starts AS s ON p.videoSeconds >= s.lo AND p.videoSeconds < s.hi
    WHERE p.matchId = @matchId AND p.videoSeconds <= @video AND p.contestantId IN (@home, @away)
    GROUP BY s.periodId, s.minute, IIF(p.contestantId = @home, 1, 0);

    INSERT @a
    SELECT actionId, periodId, timeSeconds, clockSeconds, minute, isHome, typeName, success, hx, sx, sy, ex, ey,
           IIF(nextPeriod = periodId, nextTime, NULL), IIF(possessionId IS NULL, NULL, firstAction),
           IIF(ftCand = 1 AND ROW_NUMBER() OVER (PARTITION BY periodId, ISNULL(possessionId, -1), isHome, ftCand
                                                 ORDER BY actionId) = 1, 1, 0),
           IIF(boxCand = 1 AND ROW_NUMBER() OVER (PARTITION BY periodId, ISNULL(possessionId, -1), isHome, boxCand
                                                  ORDER BY actionId) = 1, 1, 0),
           ownGoal
    FROM (SELECT a.actionId, a.periodId, a.timeSeconds, a.clockSeconds, CAST(FLOOR(a.clockSeconds / 60e0) AS int) AS minute,
                 t.isHome, a.typeName, t.success, a.possessionId, a.startX AS hx, t.sx, t.sy, t.ex, t.ey,
                 IIF(e.passLike = 1 AND t.sx < 70e0 AND t.ex >= 70e0, 1, 0) AS ftCand,
                 IIF(e.passLike = 1 AND NOT (t.sx >= 88.5e0 AND ABS(t.sy - 34e0) <= 20.16e0)
                     AND t.ex >= 88.5e0 AND ABS(t.ey - 34e0) <= 20.16e0, 1, 0) AS boxCand,
                 IIF(a.resultName = 'owngoal', 1, 0) AS ownGoal,
                 LEAD(a.periodId) OVER (ORDER BY a.actionId) AS nextPeriod,
                 LEAD(a.timeSeconds) OVER (ORDER BY a.actionId) AS nextTime,
                 MIN(a.actionId) OVER (PARTITION BY a.periodId, a.possessionId, t.isHome) AS firstAction
          FROM dbo.spadlActions AS a
          CROSS APPLY (SELECT IIF(a.teamId = @home, 1, 0) AS isHome, IIF(a.resultName = 'success', 1, 0) AS success,
                              IIF(a.teamId = @home, a.startX, 105e0 - a.startX) AS sx,
                              IIF(a.teamId = @home, a.startY, 68e0 - a.startY) AS sy,
                              IIF(a.teamId = @home, a.endX, 105e0 - a.endX) AS ex,
                              IIF(a.teamId = @home, a.endY, 68e0 - a.endY) AS ey) AS t
          CROSS APPLY (SELECT IIF(t.success = 1 AND a.typeName IN ('pass', 'cross', 'throw_in', 'freekick_crossed',
                                  'freekick_short', 'corner_crossed', 'corner_short', 'goalkick', 'dribble'), 1, 0) AS passLike) AS e
          WHERE a.matchId = @matchId AND a.finalSeq <= @seq) AS x;

    -- Ball timeline: each action's start (home frame hx) holds until the next action in its period (at most
    -- @gapCap s; @lastGap s after the period's last), split at the minute end; both teams see the same ball.
    WITH pieces AS (
        SELECT a.periodId, pc.minute, pc.s, a.hx
        FROM @a AS a
        CROSS APPLY (SELECT IIF(a.nextTime IS NULL, @lastGap, IIF(a.nextTime - a.timeSeconds < @gapCap,
                                                                  a.nextTime - a.timeSeconds, @gapCap)) AS dur) AS d
        CROSS APPLY (SELECT a.clockSeconds + d.dur AS endS, (a.minute + 1) * 60e0 AS boundary) AS t
        CROSS APPLY (VALUES (a.minute, IIF(t.endS < t.boundary, t.endS, t.boundary) - a.clockSeconds),
                            (a.minute + 1, IIF(t.boundary < t.endS - 1e-9, t.endS - t.boundary, 0e0))) AS pc (minute, s)
        WHERE d.dur > 0 AND pc.s > 0)
    INSERT @c
    SELECT p.periodId, p.minute, h.isHome, 0, SUM(p.s),
           SUM(IIF(IIF(h.isHome = 1, p.hx, 105e0 - p.hx) >= 52.5e0, p.s, 0e0)),
           SUM(IIF(IIF(h.isHome = 1, p.hx, 105e0 - p.hx) >= 70e0, p.s, 0e0)),
           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    FROM pieces AS p
    CROSS JOIN (VALUES (CAST(1 AS bit)), (CAST(0 AS bit))) AS h (isHome)
    GROUP BY p.periodId, p.minute, h.isHome;

    -- On-ball actions; entries count once per (period, possession, team); flanks are the outer two of @lanes
    -- lanes across the width, team frame (y < 68/@lanes is the right); goals are successful shots (own goals: below).
    INSERT @c
    SELECT a.periodId, a.minute, a.isHome, 0, 0, 0, 0,
           SUM(IIF(a.sx >= 70e0 AND a.typeName <> 'foul', 1, 0)),
           SUM(CAST(a.ftEntry AS int)), SUM(CAST(a.boxEntry AS int)),
           SUM(IIF(a.typeName IN ('shot', 'shot_penalty', 'shot_freekick'), 1, 0)),
           SUM(IIF(a.typeName IN ('shot', 'shot_penalty', 'shot_freekick') AND a.sx >= 88.5e0
                   AND ABS(a.sy - 34e0) <= 20.16e0, 1, 0)),
           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
           SUM(IIF(p.len IS NOT NULL, 1, 0)),
           SUM(IIF(p.len IS NOT NULL, IIF(a.ex - a.sx > 0e0, a.ex - a.sx, 0e0), 0e0)),
           SUM(ISNULL(p.len, 0e0)),
           SUM(IIF(p.len >= @longPass, 1, 0)),
           SUM(IIF(a.sx >= 52.5e0 AND a.typeName <> 'foul', 1, 0)),
           SUM(IIF(a.sx >= 52.5e0 AND a.typeName <> 'foul' AND a.sy < 68e0 / @lanes, 1, 0)),
           SUM(IIF(a.sx >= 52.5e0 AND a.typeName <> 'foul' AND a.sy > 68e0 - 68e0 / @lanes, 1, 0)),
           SUM(IIF(a.typeName IN ('shot', 'shot_penalty', 'shot_freekick') AND a.success = 1, 1, 0))
    FROM @a AS a
    CROSS APPLY (SELECT IIF(a.typeName IN ('pass', 'cross'), SQRT(SQUARE(a.ex - a.sx) + SQUARE(a.ey - a.sy)), NULL) AS len) AS p
    GROUP BY a.periodId, a.minute, a.isHome;

    -- Fast breaks: an open-play possession from the own half reaching the final third with @breakMetres of progress
    -- (or a shot) before any action more than @breakSeconds after its first; counted in the first action's minute.
    INSERT @g
    SELECT a.firstAction, a.actionId, IIF(a.timeSeconds - f.timeSeconds > @breakSeconds, 1, 0),
           IIF((r.reach >= 70e0 AND r.reach - f.sx >= @breakMetres) OR a.typeName IN ('shot', 'shot_penalty', 'shot_freekick'), 1, 0)
    FROM @a AS a
    JOIN @a AS f ON f.actionId = a.firstAction
    CROSS APPLY (SELECT IIF(a.success = 1 AND a.ex > a.sx AND a.typeName IN ('pass', 'cross', 'throw_in',
                            'freekick_crossed', 'freekick_short', 'corner_crossed', 'corner_short', 'goalkick', 'dribble',
                            'take_on'), a.ex, a.sx) AS reach) AS r
    WHERE f.sx < 52.5e0
      AND f.typeName NOT IN ('throw_in', 'freekick_crossed', 'freekick_short', 'corner_crossed', 'corner_short', 'goalkick');
    INSERT @c
    SELECT f.periodId, f.minute, f.isHome, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, COUNT(*), 0, 0, 0, 0,
           0, 0, 0, 0
    FROM (SELECT firstAction, MIN(IIF(late = 1, actionId, NULL)) AS cutoff FROM @g GROUP BY firstAction) AS c
    JOIN @a AS f ON f.actionId = c.firstAction
    WHERE EXISTS (SELECT 1 FROM @g AS g WHERE g.firstAction = c.firstAction AND g.hit = 1
                                          AND g.actionId < ISNULL(c.cutoff, 2147483647))
    GROUP BY f.periodId, f.minute, f.isHome;

    -- MA3 rows outside SPADL (Opta x is already team-relative, 0-100 → metres).
    INSERT @c
    SELECT r.periodId, (60 * r.timeMin + r.timeSec) / 60, IIF(r.contestantId = @home, 1, 0), 0, 0, 0, 0, 0, 0, 0, 0, 0,
           SUM(IIF(r.typeId = 1 AND d.xm < @buildLine, 1, 0)),
           SUM(IIF(d.defensive = 1 AND d.xm >= @pressLine, 1, 0)),
           SUM(IIF(d.defensive = 1 OR r.typeId IN (12, 49, 74), 1, 0)),
           SUM(IIF(d.defensive = 1 OR r.typeId IN (12, 49, 74), d.xm, 0e0)),
           SUM(IIF(r.typeId = 4 AND r.outcome = 0, 1, 0)), SUM(IIF(r.typeId = 17, 1, 0)),
           SUM(IIF(r.typeId = 7, 1, 0)), SUM(IIF(r.typeId = 45, 1, 0)), SUM(IIF(r.typeId = 44, 1, 0)),
           SUM(IIF(r.typeId = 3, 1, 0)), 0, 0, 0, 0, 0, 0, 0, 0, 0
    FROM dbo.rawEvents AS r
    CROSS APPLY (SELECT ISNULL(r.x, 0e0) * 105e0 / 100e0 AS xm,
                        IIF(r.typeId IN (7, 8, 45) OR (r.typeId = 4 AND r.outcome = 0), 1, 0) AS defensive) AS d
    WHERE r.matchId = @matchId AND r.eventSeq <= @seq AND r.contestantId IN (@home, @away)
      AND (r.x IS NOT NULL OR r.typeId = 17)
    GROUP BY r.periodId, (60 * r.timeMin + r.timeSec) / 60, IIF(r.contestantId = @home, 1, 0);

    -- Own goals count for the opponent; a goal overturned by VAR (MA3 type 900, qualifier 901) no longer counts
    -- (an overturned own goal was the opponent's).
    INSERT @c
    SELECT a.periodId, a.minute, IIF(a.isHome = 1, 0, 1), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
           0, 0, 0, 0, 0, 0, COUNT(*)
    FROM @a AS a WHERE a.ownGoal = 1
    GROUP BY a.periodId, a.minute, a.isHome;
    INSERT @c
    SELECT r.periodId, (60 * r.timeMin + r.timeSec) / 60, IIF(IIF(r.contestantId = @home, 1, 0) <> q.ownGoal, 1, 0),
           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -COUNT(*)
    FROM dbo.rawEvents AS r
    CROSS APPLY (SELECT IIF(EXISTS (SELECT 1 FROM OPENJSON(r.payload, '$.qualifier') WITH (qualifierId int) AS x
                                    WHERE x.qualifierId = 28), 1, 0) AS ownGoal) AS q
    WHERE r.matchId = @matchId AND r.eventSeq <= @seq AND r.typeId = 900 AND r.contestantId IN (@home, @away)
      AND EXISTS (SELECT 1 FROM OPENJSON(r.payload, '$.qualifier') WITH (qualifierId int, value nvarchar(64)) AS x
                  WHERE x.qualifierId = 901 AND x.value = N'goal-overturned')
    GROUP BY r.periodId, (60 * r.timeMin + r.timeSec) / 60, IIF(IIF(r.contestantId = @home, 1, 0) <> q.ownGoal, 1, 0);

    SELECT @terrAt = minuteAt, @terrBall = minBallSeconds FROM dbo.trendDefinitions WHERE trendId = 'territory_spell';
    SELECT @pressAt = minuteAt, @pressBall = minBallSeconds FROM dbo.trendDefinitions WHERE trendId = 'pressure_spell';

    INSERT @c  -- every minute the clock reached exists for both teams, even when empty
    SELECT m.periodId, m.minute, h.isHome, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
           0, 0, 0, 0
    FROM @minutes AS m CROSS JOIN (VALUES (CAST(1 AS bit)), (CAST(0 AS bit))) AS h (isHome);

    WITH sums AS (
        SELECT periodId, minute, isHome, SUM(possessionSeconds) AS possessionSeconds, SUM(ballSeconds) AS ballSeconds,
               SUM(attHalfSeconds) AS attHalfSeconds, SUM(finalThirdSeconds) AS finalThirdSeconds,
               SUM(ftActions) AS ftActions, SUM(ftEntries) AS ftEntries, SUM(boxEntries) AS boxEntries,
               SUM(shots) AS shots, SUM(boxShots) AS boxShots, SUM(buildPasses) AS buildPasses,
               SUM(pressActions) AS pressActions, SUM(defActions) AS defActions, SUM(defMetres) AS defMetres,
               SUM(fouls) AS fouls, SUM(cards) AS cards, SUM(tackles) AS tackles, SUM(challenges) AS challenges,
               SUM(aerials) AS aerials, SUM(takeOns) AS takeOns, SUM(fastBreaks) AS fastBreaks, SUM(passes) AS passes,
               SUM(forwardMetres) AS forwardMetres, SUM(passMetres) AS passMetres, SUM(longPasses) AS longPasses,
               SUM(attActions) AS attActions, SUM(rightActions) AS rightActions, SUM(leftActions) AS leftActions,
               SUM(goalsFor) AS goalsFor
        FROM @c
        GROUP BY periodId, minute, isHome)
    INSERT @rows
    SELECT DENSE_RANK() OVER (ORDER BY s.periodId, s.minute), s.periodId, s.minute,
           CASE WHEN s.minute + 1 > pe.endMin THEN CONCAT(pe.endMin, '+', s.minute + 1 - pe.endMin, '''')
                ELSE CONCAT(s.minute + 1, '''') END,
           s.isHome, IIF(s.isHome = 1, @home, @away),
           s.possessionSeconds, s.ballSeconds, s.attHalfSeconds, s.finalThirdSeconds, sh.att, sh.fin,
           s.ftActions, s.ftEntries, s.boxEntries, s.shots, s.boxShots, s.buildPasses, s.pressActions, s.defActions,
           s.defMetres, IIF(s.defActions > 0, s.defMetres / s.defActions, NULL), s.fouls, s.cards, s.tackles,
           s.challenges, s.aerials, s.takeOns, s.fastBreaks, s.passes, s.forwardMetres, s.passMetres, s.longPasses,
           @wFinal * s.finalThirdSeconds + @wEntry * s.ftEntries + @wBox * s.boxEntries + @wShot * s.shots, NULL,
           IIF(s.ballSeconds >= @terrBall AND sh.att >= @terrAt, 1, 0),
           IIF(s.ballSeconds >= @pressBall AND sh.fin >= @pressAt AND s.ftEntries + s.boxEntries + s.shots >= 1, 1, 0),
           s.attActions, s.rightActions, s.leftActions, s.goalsFor, 0
    FROM sums AS s
    CROSS APPLY (SELECT (s.attHalfSeconds + 1e0) / (s.ballSeconds + 2e0) AS att,
                        (s.finalThirdSeconds + 1e0) / (s.ballSeconds + 2e0) AS fin) AS sh
    CROSS APPLY (SELECT CASE s.periodId WHEN 1 THEN 45 WHEN 2 THEN 90 WHEN 3 THEN 105 ELSE 120 END AS endMin) AS pe;

    -- Game state: the team's goal difference at the start of each minute.
    UPDATE r SET leadAtStart = ISNULL((SELECT SUM(x.goalsFor - y.goalsFor) FROM @rows AS x
                                       JOIN @rows AS y ON y.rn = x.rn AND y.isHome <> x.isHome
                                       WHERE x.isHome = r.isHome AND x.rn < r.rn), 0)
    FROM @rows AS r;

    -- Momentum: EWMA (@alpha) of home-minus-away threat from kick-off; the away row carries its negative.
    SELECT @n = MAX(rn) FROM @rows;
    WHILE @i <= @n
    BEGIN
        SELECT @m = @alpha * (h.threat - a.threat) + (1e0 - @alpha) * @m
        FROM @rows AS h JOIN @rows AS a ON a.rn = h.rn AND a.isHome = 0
        WHERE h.rn = @i AND h.isHome = 1;
        UPDATE @rows SET momentum = IIF(isHome = 1, @m, -@m) WHERE rn = @i;
        SET @i += 1;
    END;
    RETURN;
END;
GO
