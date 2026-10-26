# Submission (Microsoft Innovate Studio)

## Tagline

Watch three live matches and ask any of them anything.

## Description

**Plain paragraph.** Inside the Game is a match companion for live football. Press Start and three simulated matches kick off with video and a live event feed. Pick your team and your style, and each match's story is written for you as it happens. Ask a question ("who has had more shots since half time?") and you get the number, where it came from and what it cost; ask for a moment and you get the clip. Follow a storyline and it comes back when it moves, clip included. Built in two days on simulated feeds; swap the simulator for a real provider feed and it works.

**Technical paragraph.** A simulated provider streams Opta-style events into Azure Event Hubs, and footage as HLS. Azure Stream Analytics writes key events and minute stats to Azure SQL, served as GraphQL by Data API builder. A narrative engine on Microsoft Agent Framework keeps match memory in Azure Cosmos DB, runs one pass per audience bucket on Azure AI Foundry gpt models and publishes over Azure Service Bus. The Microsoft Decision-1 decision model checks claims and decides when a story moves and which moments become clips. The user backend answers questions from ETL stats or compiles a custom stat into a validated rule DSL, all on Azure Container Apps behind a Cloudflare edge Worker; the footage is ours, rendered with Google Research Football.

Decision-1, for the video: a model that answers typed yes/no, choice or score questions with probabilities and never writes free text. Here it decides when a story moves, which moments become clips, and whether a claim in a narrative is supported by the facts.

Style rule: this must read hand-written. No "multi-agent orchestration", "cloud native", "scalable", "cost optimized".

## Video

Rules: the demo video must be **under 2:00**. Confirm the limit on the submission page before uploading a 2:30 cut; if only 2:00 counts, cut the tail.

Mechanism: screen-recorded Google Meet, both of us talking, unscripted from dot points. Demo and talking points inside 2:00; at 2:00 say "if you want to hang around, here's the architecture" and run the optional tail.

| Time | Beat |
| --- | --- |
| 0:00–0:15 | Hook: our own generated footage, three live matches starting; "every frame and every event here is ours, and the models have never seen the future" |
| 0:15–0:35 | Ask a question in chat; the answer with its facts and receipt (tokens, time, cost) |
| 0:35–0:55 | Ask for a moment; the clip plays, preview card, slow motion into the moment |
| 0:55–1:15 | Follow a story; it moves and the follow narrative arrives with its clip; Decision-1 in one sentence |
| 1:15–1:30 | Cross-game: ask about another live match from the same chat; yellow-outlined cards; "Follow this story?" |
| 1:30–1:45 | Where we'd take it next: the feed already streams player positions, so tap-a-player overlays on the footage are the next step |
| 1:45–2:00 | How it works in 20 s over the overview diagram: feed → Event Hubs → Stream Analytics → SQL → engine → Service Bus → backend → viewer; "built in two days, swap the simulator for a real feed" |
| 2:00–2:30 | Optional tail: README and the detailed architecture diagram, the Microsoft stack, honest seeds, prompt caching |

The build stays up until 10 Nov, 11:59 pm PT.

## Checklist

- [ ] Repo public
- [ ] Licence file at the root
- [ ] Screenshots: start screen, match view with cards, chat answer with receipt, follow view with clip, cross-game card, `/dev/` screen
- [ ] Video under 2:00 on public YouTube or Vimeo
- [ ] Description names the Microsoft technologies; disclosure of synthetic data and AI
- [ ] Demo URL opens for an anonymous viewer and Start demo works
- [ ] Hackathon registration and team eligibility confirmed (registration closed 20 Oct)
- [ ] Foundry quota in Australia East holds through judging (`gpt-6.1-sol` GlobalStandard 250K TPM: `writer` 120K + `questions` 130K; `gpt-6-luna` and `gpt-5-mini` 100K each; `Microsoft-Decision-1` DataZoneStandard 50 RPM)
- [ ] `BUNDLE_DENYLIST` CI secret created
- [ ] Decide whether to clean old provider and real-club names from git history
