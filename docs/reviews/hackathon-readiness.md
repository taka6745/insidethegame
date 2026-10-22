# Hackathon readiness

Reviewed **21 October 2026** against the [official rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md) and the code as it is now. This review doesn't certify eligibility or predict judging.

| | |
| --- | --- |
| **Submission closes** | 27 Oct 2026, 11:59 pm PT (28 Oct, 4:59 pm Brisbane) |
| **Judge access until** | 10 Nov 2026, 11:59 pm PT |
| **Local demo** | Three concurrent matches, live narratives, questions, replays, `/dev/` (tested locally) |
| **Azure dev** | ETL pipeline and narrative engine deployed; backend and frontend not deployed |

## 1. Brief and implementation

*In short: all five stages run locally on synthetic data; only ETL and the engine are in Azure.*

| Stage (§4.1) | Built | Status |
| --- | --- | --- |
| Ingest | Feed (simulated external provider) → Event Hubs → Stream Analytics → Azure SQL | ETL deployed; feed and multi-match ETL tested locally |
| Interpret | Stat catalogue, `statsAtSeq` and watermarks served through Data API builder | Tested locally (SQL Server + DAB) |
| Explain | Narrative engine (Agent Framework): minute summaries, compression, per-bucket authoring | Engine deployed; multi-match tested locally |
| Render | Match picker, live HLS, cards, narratives, chat replays, receipts | Tested locally |
| Personalise | 12 audience buckets (team × style), custom stats, pins | Tested locally |

## 2. Judging criteria (§6, 20% each)

*In short: the README maps each criterion to evidence; cloud deployment is the main gap.*

| Criterion | Evidence | Still needed |
| --- | --- | --- |
| Technological implementation | Service contracts, per-service tests in CI, synthetic labelled data, Terraform | Backend and frontend in Azure |
| Agentic design | Multi-agent engine with a global model gate; question agent with tools, clarification and a bounded rule DSL | A short trace in the video |
| Real-world impact | Per-match isolation and purge, future data unreachable, shared narratives per bucket | Load and recovery tests in Azure ([gaps](../../terraform/deployment-readiness.md)) |
| UX and presentation | Viewer, chat, replays, receipts | Demo video |
| Category | Foundry, Agent Framework, Event Hubs, Stream Analytics, Azure SQL, DAB, Service Bus, Cosmos DB, Container Apps | Pick the category on the form |

## 3. Submission blockers

*In short: what the repo can't fix on its own.*

| Requirement | State |
| --- | --- |
| Registration and team eligibility (§§3, 4.10) | Unknown from the repo. Registration closed 20 Oct, 12:00 pm PT. |
| Demo video under 2 minutes, public YouTube or Vimeo, no unlicensed third-party marks (§4.4) | Not recorded |
| Public GitHub repository | Repo is private |
| Working judge access, free, until 10 Nov (§4.8) | Not met: the full app runs only on localhost |
| Pitch naming the Microsoft technologies used (§4.4) | Drafted in the [README](../../README.md#judging-criteria) |
| Third-party rights (§§4.3, 4.11, 7) | Open. The league typefaces, crests (`frontend/assets/league/`) and real club and player names are not licensed. [Provenance](../../frontend/assets/league/PROVENANCE.md) is attribution, not permission. Replace them or record permission before submitting. Keep them out of the video. |
| Licence | No `LICENSE` file. The rules don't require one; choose one before making the repo public. |
| Synthetic, football-realistic data (§4.7) | Met: GRF simulations, labelled ([recordings](../../data-generation/recordings/README.md)) |
| Open-source compliance (§4.11) | GRF (Apache-2.0) credited; check other bundled assets |
| AI disclosure | Not required; the README discloses AI-generated narratives and answers |
