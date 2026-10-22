# The Match Desk

Synthetic football insights with inspectable evidence and explicit corrections.
Built from scratch for Inside the Game. Starter project, not a completed AI submission.

## Run locally

Requires Python 3.11 or newer. No pip packages or Azure credentials are needed for this starter.

```bash
python3 -m matchdesk.server
```

Open http://127.0.0.1:8000. Play or step through the match. Expand a metric card to inspect its evidence. Correct a non-goal shot to a pass and observe the updated count and correction history. Rewind changes the playback clock; it does not undo corrections. Browser sessions are isolated.

```bash
python3 -m unittest discover -s tests -v
```

## Implemented

- Seeded, fictional event generation and progressive replay.
- Event-derived score, passes and shots.
- Exact structured shot-claim validation by team, window and evidence IDs.
- Analyst/casual template variants, timed JSON cards and full-time factual recap.
- Explicit non-goal shot correction and audit record.
- Duplicate detection and isolated local browser sessions.

## Not implemented yet

- Microsoft Foundry calls and the three AI agents.
- Semantic verification of free-form explanations.
- Turning-point analysis, pressures and tackles, realistic possession continuity.
- isiZulu and Setswana, persisted sessions and Azure deployment.
- Published insight version storage, targeted retraction and latency/cost evaluation.

The interface labels all current output as deterministic templates. A true metric does not establish a tactical cause. The simulator is illustrative, not calibrated; its duration varies by seed and is not yet a full 90-minute match.

## Proposed next increment

Analyst retrieves current events and stats; Story Editor drafts; Reviewer inspects the final wording. Deterministic checks enforce supported numerical claims. Integrate and evaluate real Foundry agents before describing this as multi-agent AI. See docs/architecture.md and docs/backlog.md.

## Local security and limits

This stdlib server is for development. Sessions are in memory (maximum 100), lost on restart, and do not support multiple replicas. Do not expose it directly as a production service. Add production serving, session expiry, authentication for producer writes, durable state, rate limiting and managed identity before Azure deployment. No secrets belong in the browser or repository.

## Docker

```bash
docker build -t the-match-desk .
docker run --rm -p 8000:8000 the-match-desk
```

## Get the project from GitHub

```bash
git clone https://github.com/Banelenelson02/The-match-desk.git
cd The-match-desk
python3 -m matchdesk.server
```

If using the starter ZIP, first enter its inner `the-match-desk` folder. Run the command from the directory containing `matchdesk/` and `web/`.

All teams and players are fictional. No competitor code, real footage or real match datasets are included.
