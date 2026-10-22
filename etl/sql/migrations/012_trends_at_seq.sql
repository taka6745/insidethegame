-- Trend indicators at a snapshot (local/contracts.md §3, §4b): trendMinutesAtSeq (per minute and team),
-- trendsAtSeq (indicator × team × window) and trendSpellsAtSeq (territory and pressure spells). Read-time: each
-- call recomputes from the rows final at (matchId, seq), so a backlog read equals the live one. Empty for an
-- unknown or purged match, or for a seq above the watermark or above spadlSeq (retry), never a partial set.
-- Formulas (the S1 storylines experiment) are documented in §4b; thresholds come from dbo.trendDefinitions (011).
-- reference/trends.py is the executable twin; tests compare them on every recording.

-- One row per minute (match order) and team: the components every trend reads.
IF TYPE_ID(N'dbo.trendMinute') IS NULL CREATE TYPE dbo.trendMinute AS TABLE (
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
    PRIMARY KEY (rn, isHome)
);
GO

-- Sources at the snapshot: minutes and their start video time from canonicalEvents (seq <= @seq); possession
-- from POS samples up to its video time, each in the minute it ends in; ball timeline, on-ball actions, entries
-- and fast breaks from spadlActions (finalSeq <= @seq); defensive actions, fouls and cards from MA3 rawEvents
-- (eventSeq <= @seq). Team frame: the team attacks towards x = 105.
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
    PRIMARY KEY (rn, isHome))
AS
BEGIN
    DECLARE @home nvarchar(64), @away nvarchar(64), @video float, @i int = 1, @n int, @m float = 0,
            @terrAt float, @terrBall float, @pressAt float, @pressBall float;
    SELECT @home = m.homeContestantId, @away = m.awayContestantId
    FROM dbo.matches AS m
    LEFT JOIN dbo.matchProgress AS p ON p.matchId = m.matchId
    LEFT JOIN dbo.spadlProgress AS sp ON sp.matchId = m.matchId
    WHERE m.matchId = @matchId AND @seq >= 0 AND @seq <= ISNULL(p.seq, 0) AND @seq <= ISNULL(sp.seq, 0);
    IF @home IS NULL RETURN;

    DECLARE @minutes TABLE (periodId int NOT NULL, minute int NOT NULL, startVideo float NULL, PRIMARY KEY (periodId, minute));
    DECLARE @starts TABLE (periodId int NOT NULL, minute int NOT NULL, lo float NOT NULL, hi float NOT NULL, PRIMARY KEY (lo));
    -- Final actions in the team frame, with what the window functions give once: the next action's time in the
    -- same period, the first action of the possession chain (period, possession, team) and first entries.
    DECLARE @a TABLE (actionId int PRIMARY KEY, periodId int NOT NULL, timeSeconds float NOT NULL,
                      clockSeconds float NOT NULL, minute int NOT NULL, isHome bit NOT NULL, typeName nvarchar(20) NOT NULL,
                      success bit NOT NULL, hx float NOT NULL, sx float NOT NULL, sy float NOT NULL, ex float NOT NULL,
                      ey float NOT NULL, nextTime float NULL, firstAction int NULL, ftEntry bit NOT NULL, boxEntry bit NOT NULL);
    DECLARE @g TABLE (firstAction int NOT NULL, actionId int NOT NULL, late bit NOT NULL, hit bit NOT NULL,
                      PRIMARY KEY (firstAction, actionId));
    -- Components: one row per source and (minute, team); summed below.
    DECLARE @c TABLE (periodId int NOT NULL, minute int NOT NULL, isHome bit NOT NULL, possessionSeconds float NOT NULL,
                      ballSeconds float NOT NULL, attHalfSeconds float NOT NULL, finalThirdSeconds float NOT NULL,
                      ftActions int NOT NULL, ftEntries int NOT NULL, boxEntries int NOT NULL, shots int NOT NULL,
                      boxShots int NOT NULL, buildPasses int NOT NULL, pressActions int NOT NULL, defActions int NOT NULL,
                      defMetres float NOT NULL, fouls int NOT NULL, cards int NOT NULL, tackles int NOT NULL,
                      challenges int NOT NULL, aerials int NOT NULL, takeOns int NOT NULL, fastBreaks int NOT NULL,
                      passes int NOT NULL, forwardMetres float NOT NULL, passMetres float NOT NULL, longPasses int NOT NULL);

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
               tackles, challenges, aerials, takeOns, fastBreaks, passes, forwardMetres, passMetres, longPasses)
    SELECT s.periodId, s.minute, IIF(p.contestantId = @home, 1, 0), SUM(p.durationSeconds),
           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
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
                                                  ORDER BY actionId) = 1, 1, 0)
    FROM (SELECT a.actionId, a.periodId, a.timeSeconds, a.clockSeconds, CAST(FLOOR(a.clockSeconds / 60e0) AS int) AS minute,
                 t.isHome, a.typeName, t.success, a.possessionId, a.startX AS hx, t.sx, t.sy, t.ex, t.ey,
                 IIF(e.passLike = 1 AND t.sx < 70e0 AND t.ex >= 70e0, 1, 0) AS ftCand,
                 IIF(e.passLike = 1 AND NOT (t.sx >= 88.5e0 AND ABS(t.sy - 34e0) <= 20.16e0)
                     AND t.ex >= 88.5e0 AND ABS(t.ey - 34e0) <= 20.16e0, 1, 0) AS boxCand,
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
    -- 8 s; 1 s after the period's last), split at the minute end; both teams see the same ball.
    WITH pieces AS (
        SELECT a.periodId, pc.minute, pc.s, a.hx
        FROM @a AS a
        CROSS APPLY (SELECT IIF(a.nextTime IS NULL, 1e0, IIF(a.nextTime - a.timeSeconds < 8e0,
                                                             a.nextTime - a.timeSeconds, 8e0)) AS dur) AS d
        CROSS APPLY (SELECT a.clockSeconds + d.dur AS endS, (a.minute + 1) * 60e0 AS boundary) AS t
        CROSS APPLY (VALUES (a.minute, IIF(t.endS < t.boundary, t.endS, t.boundary) - a.clockSeconds),
                            (a.minute + 1, IIF(t.boundary < t.endS - 1e-9, t.endS - t.boundary, 0e0))) AS pc (minute, s)
        WHERE d.dur > 0 AND pc.s > 0)
    INSERT @c
    SELECT p.periodId, p.minute, h.isHome, 0, SUM(p.s),
           SUM(IIF(IIF(h.isHome = 1, p.hx, 105e0 - p.hx) >= 52.5e0, p.s, 0e0)),
           SUM(IIF(IIF(h.isHome = 1, p.hx, 105e0 - p.hx) >= 70e0, p.s, 0e0)),
           0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    FROM pieces AS p
    CROSS JOIN (VALUES (CAST(1 AS bit)), (CAST(0 AS bit))) AS h (isHome)
    GROUP BY p.periodId, p.minute, h.isHome;

    -- On-ball actions; entries count once per (period, possession, team).
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
           SUM(IIF(p.len >= 32e0, 1, 0))
    FROM @a AS a
    CROSS APPLY (SELECT IIF(a.typeName IN ('pass', 'cross'), SQRT(SQUARE(a.ex - a.sx) + SQUARE(a.ey - a.sy)), NULL) AS len) AS p
    GROUP BY a.periodId, a.minute, a.isHome;

    -- Fast breaks: an open-play possession from the own half reaching the final third with 30 m of progress
    -- (or a shot) before any action more than 12 s after its first; counted in the first action's minute.
    INSERT @g
    SELECT a.firstAction, a.actionId, IIF(a.timeSeconds - f.timeSeconds > 12e0, 1, 0),
           IIF((r.reach >= 70e0 AND r.reach - f.sx >= 30e0) OR a.typeName IN ('shot', 'shot_penalty', 'shot_freekick'), 1, 0)
    FROM @a AS a
    JOIN @a AS f ON f.actionId = a.firstAction
    CROSS APPLY (SELECT IIF(a.success = 1 AND a.ex > a.sx AND a.typeName IN ('pass', 'cross', 'throw_in',
                            'freekick_crossed', 'freekick_short', 'corner_crossed', 'corner_short', 'goalkick', 'dribble',
                            'take_on'), a.ex, a.sx) AS reach) AS r
    WHERE f.sx < 52.5e0
      AND f.typeName NOT IN ('throw_in', 'freekick_crossed', 'freekick_short', 'corner_crossed', 'corner_short', 'goalkick');
    INSERT @c
    SELECT f.periodId, f.minute, f.isHome, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, COUNT(*), 0, 0, 0, 0
    FROM (SELECT firstAction, MIN(IIF(late = 1, actionId, NULL)) AS cutoff FROM @g GROUP BY firstAction) AS c
    JOIN @a AS f ON f.actionId = c.firstAction
    WHERE EXISTS (SELECT 1 FROM @g AS g WHERE g.firstAction = c.firstAction AND g.hit = 1
                                          AND g.actionId < ISNULL(c.cutoff, 2147483647))
    GROUP BY f.periodId, f.minute, f.isHome;

    -- MA3 rows outside SPADL (Opta x is already team-relative, 0-100 → metres).
    INSERT @c
    SELECT r.periodId, (60 * r.timeMin + r.timeSec) / 60, IIF(r.contestantId = @home, 1, 0), 0, 0, 0, 0, 0, 0, 0, 0, 0,
           SUM(IIF(r.typeId = 1 AND d.xm < 63e0, 1, 0)),
           SUM(IIF(d.defensive = 1 AND d.xm >= 42e0, 1, 0)),
           SUM(IIF(d.defensive = 1 OR r.typeId IN (12, 49, 74), 1, 0)),
           SUM(IIF(d.defensive = 1 OR r.typeId IN (12, 49, 74), d.xm, 0e0)),
           SUM(IIF(r.typeId = 4 AND r.outcome = 0, 1, 0)), SUM(IIF(r.typeId = 17, 1, 0)),
           SUM(IIF(r.typeId = 7, 1, 0)), SUM(IIF(r.typeId = 45, 1, 0)), SUM(IIF(r.typeId = 44, 1, 0)),
           SUM(IIF(r.typeId = 3, 1, 0)), 0, 0, 0, 0, 0
    FROM dbo.rawEvents AS r
    CROSS APPLY (SELECT ISNULL(r.x, 0e0) * 105e0 / 100e0 AS xm,
                        IIF(r.typeId IN (7, 8, 45) OR (r.typeId = 4 AND r.outcome = 0), 1, 0) AS defensive) AS d
    WHERE r.matchId = @matchId AND r.eventSeq <= @seq AND r.contestantId IN (@home, @away)
      AND (r.x IS NOT NULL OR r.typeId = 17)
    GROUP BY r.periodId, (60 * r.timeMin + r.timeSec) / 60, IIF(r.contestantId = @home, 1, 0);

    SELECT @terrAt = minuteAt, @terrBall = minBallSeconds FROM dbo.trendDefinitions WHERE trendId = 'territory_spell';
    SELECT @pressAt = minuteAt, @pressBall = minBallSeconds FROM dbo.trendDefinitions WHERE trendId = 'pressure_spell';

    INSERT @c  -- every minute the clock reached exists for both teams, even when empty
    SELECT m.periodId, m.minute, h.isHome, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    FROM @minutes AS m CROSS JOIN (VALUES (CAST(1 AS bit)), (CAST(0 AS bit))) AS h (isHome);

    WITH sums AS (
        SELECT periodId, minute, isHome, SUM(possessionSeconds) AS possessionSeconds, SUM(ballSeconds) AS ballSeconds,
               SUM(attHalfSeconds) AS attHalfSeconds, SUM(finalThirdSeconds) AS finalThirdSeconds,
               SUM(ftActions) AS ftActions, SUM(ftEntries) AS ftEntries, SUM(boxEntries) AS boxEntries,
               SUM(shots) AS shots, SUM(boxShots) AS boxShots, SUM(buildPasses) AS buildPasses,
               SUM(pressActions) AS pressActions, SUM(defActions) AS defActions, SUM(defMetres) AS defMetres,
               SUM(fouls) AS fouls, SUM(cards) AS cards, SUM(tackles) AS tackles, SUM(challenges) AS challenges,
               SUM(aerials) AS aerials, SUM(takeOns) AS takeOns, SUM(fastBreaks) AS fastBreaks, SUM(passes) AS passes,
               SUM(forwardMetres) AS forwardMetres, SUM(passMetres) AS passMetres, SUM(longPasses) AS longPasses
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
           0.02e0 * s.finalThirdSeconds + s.ftEntries + 2 * s.boxEntries + 3 * s.shots, NULL,
           IIF(s.ballSeconds >= @terrBall AND sh.att >= @terrAt, 1, 0),
           IIF(s.ballSeconds >= @pressBall AND sh.fin >= @pressAt AND s.ftEntries + s.boxEntries + s.shots >= 1, 1, 0)
    FROM sums AS s
    CROSS APPLY (SELECT (s.attHalfSeconds + 1e0) / (s.ballSeconds + 2e0) AS att,
                        (s.finalThirdSeconds + 1e0) / (s.ballSeconds + 2e0) AS fin) AS sh
    CROSS APPLY (SELECT CASE s.periodId WHEN 1 THEN 45 WHEN 2 THEN 90 WHEN 3 THEN 105 ELSE 120 END AS endMin) AS pe;

    -- Momentum: EWMA (alpha 0.4) of home-minus-away threat from kick-off; the away row carries its negative.
    SELECT @n = MAX(rn) FROM @rows;
    WHILE @i <= @n
    BEGIN
        SELECT @m = 0.4e0 * (h.threat - a.threat) + 0.6e0 * @m
        FROM @rows AS h JOIN @rows AS a ON a.rn = h.rn AND a.isHome = 0
        WHERE h.rn = @i AND h.isHome = 1;
        UPDATE @rows SET momentum = IIF(isHome = 1, @m, -@m) WHERE rn = @i;
        SET @i += 1;
    END;
    RETURN;
END;
GO

-- Per minute and team (home first), in match order: the components, momentum and spell minute flags.
CREATE OR ALTER PROCEDURE dbo.trendMinutesAtSeq @matchId nvarchar(64), @seq int
AS
SET NOCOUNT ON;
DECLARE @rows dbo.trendMinute;
INSERT @rows SELECT * FROM dbo.trendMinuteRows(@matchId, @seq);
SELECT periodId, minute, minuteLabel, contestantId, possessionSeconds, ballSeconds, attHalfSeconds, finalThirdSeconds,
       attHalfShare, finalThirdShare, ftActions, ftEntries, boxEntries, shots, boxShots, buildPasses, pressActions,
       defActions, defHeight, fouls, cards, tackles, challenges, aerials, takeOns, fastBreaks, passes, forwardMetres,
       passMetres, longPasses, threat, momentum, territoryMinute, pressureMinute
FROM @rows
ORDER BY rn, isHome DESC;
GO

-- Indicator × team × window. Windows: the current period's last 5 minutes (last5), the 10 before them (prev10),
-- its last 15 (last15), the current period (half) and the match; baselines: last5 ← prev10, last15 ← the match
-- before it, half ← the previous period. Flags only for enabled definitions and full windows (prev10 10 minutes,
-- last15 15, others 5); change flags also need 10 baseline minutes. Momentum: one last5 row per team (now vs the minute before last5).
CREATE OR ALTER PROCEDURE dbo.trendsAtSeq @matchId nvarchar(64), @seq int
AS
SET NOCOUNT ON;
DECLARE @rows dbo.trendMinute, @last int, @period int, @before int, @home nvarchar(64), @away nvarchar(64);
DECLARE @win TABLE (win nvarchar(8) NOT NULL, rn int NOT NULL, PRIMARY KEY (win, rn));
DECLARE @agg TABLE (win nvarchar(8) NOT NULL, isHome bit NOT NULL, minutes int NOT NULL, fromRn int NOT NULL,
                    toRn int NOT NULL, poss float, oppPoss float, ball float, att float, fin float, ftA int, oppFtA int,
                    ftE int, oppFtE int, boxE int, shots int, oppShots int, boxShots int, oppBuild int, press int,
                    defN int, defM float, fouls int, cards int, tackles int, challenges int, aerials int, takeOns int,
                    fb int, passes int, fwd float, len float, long int, PRIMARY KEY (win, isHome));
DECLARE @vals TABLE (win nvarchar(8) NOT NULL, isHome bit NOT NULL, trendId nvarchar(40) NOT NULL, value float NULL,
                     PRIMARY KEY (win, isHome, trendId));

INSERT @rows SELECT * FROM dbo.trendMinuteRows(@matchId, @seq);
SELECT @last = MAX(rn) FROM @rows;
SELECT @period = periodId FROM @rows WHERE rn = @last AND isHome = 1;
SELECT @home = contestantId FROM @rows WHERE rn = 1 AND isHome = 1;
SELECT @away = contestantId FROM @rows WHERE rn = 1 AND isHome = 0;

WITH k AS (SELECT rn, periodId FROM @rows WHERE isHome = 1),
cur AS (SELECT rn, ROW_NUMBER() OVER (ORDER BY rn DESC) AS fromEnd FROM k WHERE periodId = @period)
INSERT @win
SELECT 'last5', rn FROM cur WHERE fromEnd <= 5
UNION ALL SELECT 'prev10', rn FROM cur WHERE fromEnd BETWEEN 6 AND 15
UNION ALL SELECT 'last15', rn FROM cur WHERE fromEnd <= 15
UNION ALL SELECT 'pre15', rn FROM k WHERE rn < (SELECT MIN(rn) FROM cur WHERE fromEnd <= 15)
UNION ALL SELECT 'half', rn FROM cur
UNION ALL SELECT 'prevHalf', rn FROM k WHERE periodId = @period - 1
UNION ALL SELECT 'match', rn FROM k;
SELECT @before = rn FROM @win WHERE win = 'prev10' AND rn = (SELECT MAX(rn) FROM @win WHERE win = 'prev10');

INSERT @agg
SELECT w.win, t.isHome, COUNT(*), MIN(w.rn), MAX(w.rn), SUM(t.possessionSeconds), SUM(o.possessionSeconds),
       SUM(t.ballSeconds), SUM(t.attHalfSeconds), SUM(t.finalThirdSeconds), SUM(t.ftActions), SUM(o.ftActions),
       SUM(t.ftEntries), SUM(o.ftEntries), SUM(t.boxEntries), SUM(t.shots), SUM(o.shots), SUM(t.boxShots),
       SUM(o.buildPasses), SUM(t.pressActions), SUM(t.defActions), SUM(t.defMetres), SUM(t.fouls), SUM(t.cards),
       SUM(t.tackles), SUM(t.challenges), SUM(t.aerials), SUM(t.takeOns), SUM(t.fastBreaks), SUM(t.passes),
       SUM(t.forwardMetres), SUM(t.passMetres), SUM(t.longPasses)
FROM @win AS w
JOIN @rows AS t ON t.rn = w.rn
JOIN @rows AS o ON o.rn = w.rn AND o.isHome <> t.isHome
GROUP BY w.win, t.isHome;

INSERT @vals
SELECT g.win, g.isHome, v.trendId, v.value
FROM @agg AS g
CROSS APPLY (SELECT (g.poss + 1e0) / (g.poss + g.oppPoss + 2e0) AS possession,
                    (g.ftA + 1e0) / (g.ftA + g.oppFtA + 2e0) AS tilt,
                    (g.att + 1e0) / (g.ball + 2e0) AS att,
                    CAST(g.minutes AS float) AS n) AS b
CROSS APPLY (VALUES
    ('possession', b.possession),
    ('field_tilt', b.tilt),
    ('att_half_share', b.att),
    ('final_third_share', (g.fin + 1e0) / (g.ball + 2e0)),
    ('def_height', IIF(g.defN > 0, g.defM / g.defN, NULL)),
    ('box_entries', g.boxE / b.n * 5e0),
    ('shots', g.shots / b.n * 5e0),
    ('box_shots', g.boxShots / b.n * 5e0),
    ('ft_entries', g.ftE / b.n * 5e0),
    ('fouls', g.fouls / b.n * 5e0),
    ('cards', g.cards / b.n * 5e0),
    ('ppda', (g.oppBuild + 1e0) / (g.press + 1e0)),
    ('contests', (g.tackles + g.challenges + g.aerials + g.takeOns) / b.n * 5e0),
    ('aggression', (g.fouls + 3 * g.cards + 0.5e0 * (g.tackles + g.challenges)) / b.n * 5e0),
    ('fast_breaks', g.fb / b.n * 5e0),
    ('directness', (g.fwd + 1e0) / (g.len + 2e0)),
    ('long_ball_share', (g.long + 1e0) / (g.passes + 2e0)),
    ('dominance', 2e0 * ((b.possession + b.tilt + b.att + (g.shots + 1e0) / (g.shots + g.oppShots + 2e0)
                          + (g.ftE + 1e0) / (g.ftE + g.oppFtE + 2e0)) / 5e0 - 0.5e0))) AS v (trendId, value);

WITH served AS (
    SELECT d.trendId, d.family, d.label, d.unit, d.enabled, d.notableAt, d.highAt, d.changeAt, d.displayOrder,
           g.isHome, g.win, g.minutes, g.fromRn, g.toRn, v.value, bv.value AS baseline, bg.minutes AS baselineMinutes
    FROM dbo.trendDefinitions AS d
    JOIN @vals AS v ON v.trendId = d.trendId
    JOIN @agg AS g ON g.win = v.win AND g.isHome = v.isHome
    LEFT JOIN @agg AS bg ON bg.isHome = g.isHome AND bg.win = CASE g.win WHEN 'last5' THEN 'prev10'
                                                                         WHEN 'last15' THEN 'pre15'
                                                                         WHEN 'half' THEN 'prevHalf' END
    LEFT JOIN @vals AS bv ON bv.win = bg.win AND bv.isHome = g.isHome AND bv.trendId = d.trendId
    WHERE d.family IN ('indicator', 'composite') AND g.win IN ('last5', 'last15', 'prev10', 'half', 'match')
    UNION ALL
    SELECT d.trendId, d.family, d.label, d.unit, d.enabled, d.notableAt, d.highAt, d.changeAt, d.displayOrder,
           g.isHome, g.win, g.minutes, g.fromRn, g.toRn, now.momentum, b.momentum, ISNULL(p.minutes, 0)
    FROM dbo.trendDefinitions AS d
    JOIN @agg AS g ON g.win = 'last5'
    JOIN @rows AS now ON now.rn = @last AND now.isHome = g.isHome
    LEFT JOIN @rows AS b ON b.rn = @before AND b.isHome = g.isHome
    LEFT JOIN @agg AS p ON p.win = 'prev10' AND p.isHome = g.isHome
    WHERE d.family = 'momentum')
SELECT s.trendId, s.family, s.label, s.unit, IIF(s.isHome = 1, @home, @away) AS contestantId, s.win AS [window],
       s.minutes, f.minuteLabel AS fromLabel, t.minuteLabel AS toLabel, s.value, s.baseline, x.delta, l.level, l.change,
       CAST(IIF(l.level = 'high' OR l.change IS NOT NULL, 1, 0) AS bit) AS flagged, s.enabled
FROM served AS s
JOIN @rows AS f ON f.rn = s.fromRn AND f.isHome = 1
JOIN @rows AS t ON t.rn = s.toRn AND t.isHome = 1
CROSS APPLY (SELECT s.value - s.baseline AS delta,
                    s.minutes - CASE s.win WHEN 'prev10' THEN 10 WHEN 'last15' THEN 15 ELSE 5 END AS spare) AS x
CROSS APPLY (SELECT CASE WHEN s.enabled = 0 OR s.value IS NULL OR x.spare < 0 THEN NULL
                         WHEN s.value >= s.highAt THEN 'high'
                         WHEN s.value >= s.notableAt THEN 'notable' END AS level,
                    CASE WHEN s.enabled = 0 OR x.spare < 0 OR s.baselineMinutes < 10 OR ABS(x.delta) < s.changeAt
                              OR x.delta IS NULL OR s.changeAt IS NULL THEN NULL
                         WHEN x.delta > 0 THEN 'rising' ELSE 'falling' END AS change) AS l
ORDER BY s.isHome DESC, s.displayOrder,
         CASE s.win WHEN 'last5' THEN 1 WHEN 'last15' THEN 2 WHEN 'prev10' THEN 3 WHEN 'half' THEN 4 ELSE 5 END;
GO

-- Territory and pressure spells: maximal runs of flagged minutes (trendMinuteRows) within a period that bridge
-- single unflagged minutes, at least minMinutes long; ordered by start, home first.
CREATE OR ALTER PROCEDURE dbo.trendSpellsAtSeq @matchId nvarchar(64), @seq int
AS
SET NOCOUNT ON;
DECLARE @rows dbo.trendMinute, @last int;
INSERT @rows SELECT * FROM dbo.trendMinuteRows(@matchId, @seq);
SELECT @last = MAX(rn) FROM @rows;

WITH flagged AS (
    SELECT d.trendId, d.displayOrder, d.minMinutes, d.enabled, r.isHome, r.rn, r.periodId,
           IIF(LAG(r.rn) OVER (PARTITION BY d.trendId, r.isHome, r.periodId ORDER BY r.rn) >= r.rn - 2, 0, 1) AS starts
    FROM dbo.trendDefinitions AS d
    JOIN @rows AS r ON (d.trendId = 'territory_spell' AND r.territoryMinute = 1)
                    OR (d.trendId = 'pressure_spell' AND r.pressureMinute = 1)
    WHERE d.family = 'spell'),
chained AS (
    SELECT *, SUM(starts) OVER (PARTITION BY trendId, isHome ORDER BY rn ROWS UNBOUNDED PRECEDING) AS chain
    FROM flagged),
spells AS (
    SELECT trendId, displayOrder, minMinutes, enabled, isHome, periodId, MIN(rn) AS fromRn, MAX(rn) AS toRn
    FROM chained
    GROUP BY trendId, displayOrder, minMinutes, enabled, isHome, periodId, chain)
SELECT s.trendId, MIN(r.contestantId) AS contestantId, s.periodId, MIN(f.minuteLabel) AS fromLabel,
       MIN(t.minuteLabel) AS toLabel, s.toRn - s.fromRn + 1 AS minutes,
       SUM(IIF(s.trendId = 'territory_spell', r.attHalfSeconds, r.finalThirdSeconds))
           / IIF(SUM(r.ballSeconds) > 1e0, SUM(r.ballSeconds), 1e0) AS zoneShare,
       SUM(r.shots) AS shots, SUM(r.boxEntries) AS boxEntries, CAST(IIF(s.toRn = @last, 1, 0) AS bit) AS ongoing,
       s.enabled
FROM spells AS s
JOIN @rows AS r ON r.isHome = s.isHome AND r.rn BETWEEN s.fromRn AND s.toRn
JOIN @rows AS f ON f.rn = s.fromRn AND f.isHome = s.isHome
JOIN @rows AS t ON t.rn = s.toRn AND t.isHome = s.isHome
WHERE s.toRn - s.fromRn + 1 >= s.minMinutes
GROUP BY s.trendId, s.displayOrder, s.enabled, s.isHome, s.periodId, s.fromRn, s.toRn
ORDER BY s.fromRn, s.isHome DESC, s.displayOrder;
GO
