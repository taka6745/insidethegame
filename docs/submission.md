# Submission

**Watch three live matches and ask any of them anything.**

## Description

Inside the Game is for the questions that come up while you’re watching football. Who has had more shots since half time? Can I see that moment again? Watch, ask, replay or follow a developing story across three matches. Choose commentary to suit your team and style; answers include supporting facts and estimated model cost.

The application uses fictional teams and synthetic footage rendered with Google Research Football. Recorded video and events stream at match pace; AI writes the commentary and answers.

Opta-style events flow through Azure Event Hubs and Stream Analytics into Azure SQL, with history and statistics served through Data API builder GraphQL. Microsoft Agent Framework coordinates narrative agents on Azure AI Foundry. They share match analysis, keep memory in Cosmos DB and write updates per audience group. Service Bus delivers the narratives; Microsoft Decision-1 checks claims, detects story developments and selects clip moments.

Questions take a separate backend path: standard statistics come from ETL; custom requests become validated, bounded rules executed by code. Answers use data available at the viewer’s position; other matches use their own positions. Services run on Azure Container Apps behind a Cloudflare Worker.

## Video

Screen-recorded conversation and product walkthrough, **under 2:00**. Recheck the official submission rules before uploading.

| Time | Show |
| --- | --- |
| 0:00–0:15 | Three synthetic matches; explain the companion |
| 0:15–0:35 | Question → facts and cost receipt |
| 0:35–0:55 | Replay → clip |
| 0:55–1:15 | Follow → story update; explain Decision-1 |
| 1:15–1:35 | Cross-match question or all-goals reel |
| 1:35–1:55 | [Architecture](../architecture.svg); next step: player overlays |

## Checklist

- [ ] Public repo and root licence
- [ ] Screenshots: start, viewer, answer receipt, follow, cross-match, `/dev/`
- [ ] Public YouTube/Vimeo video under 2:00
- [ ] Description names Microsoft technologies and discloses synthetic data/AI
- [ ] Viewer can open the application and watch a match
- [ ] Registration, team eligibility and official rules confirmed
- [ ] Foundry quota holds through judging ([configuration](../terraform/foundry.tf))
- [ ] `BUNDLE_DENYLIST` CI secret created
- [ ] Review git history for old provider and real-club names

[Application status](../README.md#status) · [Full plan](../plan.excalidraw)
