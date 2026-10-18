-- Running match statistics: one row per match, contestant and match minute, holding
-- totals as of the end of that minute. Filter by minute for "as of"; take the latest
-- minute for current stats. Mirrors etltools/pipeline.py stats_as_of.
CREATE OR ALTER VIEW dbo.matchStatsAsOf AS
WITH perMinute AS (
    SELECT matchId, contestantId, periodId, timeMin,
           SUM(passes) AS passes, SUM(passesCompleted) AS passesCompleted, SUM(shots) AS shots,
           SUM(shotsOnTarget) AS shotsOnTarget, SUM(goals) AS goals, SUM(ownGoals) AS ownGoals,
           SUM(corners) AS corners, SUM(fouls) AS fouls, SUM(yellowCards) AS yellowCards,
           SUM(redCards) AS redCards, SUM(events) AS events
    FROM dbo.minuteStats
    GROUP BY matchId, contestantId, periodId, timeMin
),
teams AS (
    SELECT matchId, contestantId FROM dbo.minuteStats
    UNION SELECT matchId, homeContestantId FROM dbo.matches
    UNION SELECT matchId, awayContestantId FROM dbo.matches
),
grid AS (
    -- Every minute with any event, for both contestants, so quiet minutes keep their totals.
    SELECT m.matchId, t.contestantId, m.periodId, m.timeMin
    FROM (SELECT DISTINCT matchId, periodId, timeMin FROM dbo.minuteStats) AS m
    JOIN teams AS t ON t.matchId = m.matchId
),
running AS (
    SELECT g.matchId, g.contestantId, g.periodId, g.timeMin,
           SUM(ISNULL(p.passes, 0))          OVER w AS passes,
           SUM(ISNULL(p.passesCompleted, 0)) OVER w AS passesCompleted,
           SUM(ISNULL(p.shots, 0))           OVER w AS shots,
           SUM(ISNULL(p.shotsOnTarget, 0))   OVER w AS shotsOnTarget,
           SUM(ISNULL(p.goals, 0))           OVER w AS goals,
           SUM(ISNULL(p.ownGoals, 0))        OVER w AS ownGoals,
           SUM(ISNULL(p.corners, 0))         OVER w AS corners,
           SUM(ISNULL(p.fouls, 0))           OVER w AS fouls,
           SUM(ISNULL(p.yellowCards, 0))     OVER w AS yellowCards,
           SUM(ISNULL(p.redCards, 0))        OVER w AS redCards,
           SUM(ISNULL(p.events, 0))          OVER w AS events
    FROM grid AS g
    LEFT JOIN perMinute AS p
      ON p.matchId = g.matchId AND p.contestantId = g.contestantId
     AND p.periodId = g.periodId AND p.timeMin = g.timeMin
    WINDOW w AS (PARTITION BY g.matchId, g.contestantId ORDER BY g.periodId, g.timeMin ROWS UNBOUNDED PRECEDING)
)
SELECT r.matchId,
       r.contestantId,
       CASE r.contestantId WHEN m.homeContestantId THEN 'home' WHEN m.awayContestantId THEN 'away' END AS position,
       r.periodId,
       r.timeMin,
       CASE WHEN r.timeMin + 1 > pe.endMin
            THEN CONCAT(pe.endMin, '+', r.timeMin + 1 - pe.endMin, '''')
            ELSE CONCAT(r.timeMin + 1, '''') END AS minuteLabel,
       r.goals + ISNULL(o.ownGoals, 0) AS goals,
       r.ownGoals,
       r.passes, r.passesCompleted, r.shots, r.shotsOnTarget, r.corners, r.fouls,
       r.yellowCards, r.redCards, r.events,
       CAST(ROUND(100.0 * r.passes / NULLIF(r.passes + ISNULL(o.passes, 0), 0), 1) AS decimal(4, 1)) AS possessionPct
FROM running AS r
LEFT JOIN running AS o
  ON o.matchId = r.matchId AND o.periodId = r.periodId AND o.timeMin = r.timeMin AND o.contestantId <> r.contestantId
LEFT JOIN dbo.matches AS m ON m.matchId = r.matchId
CROSS APPLY (SELECT CASE r.periodId WHEN 1 THEN 45 WHEN 2 THEN 90 WHEN 3 THEN 105 ELSE 120 END AS endMin) AS pe;
GO
