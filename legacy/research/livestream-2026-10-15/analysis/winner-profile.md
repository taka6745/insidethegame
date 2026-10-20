# Winner profile

Blind synthesis from the Reactor livestream (uploaded 15 Oct 2026; runbook date 14 Oct, 9–10 AM PT), given by Brian Benz, Microsoft principal AI advocate, plus his reference repo and the official rules. Our own entry was not read.

Key: **[E]** stated in a source · **[I]** inferred. Sources: `[N]` = video minute (transcript prefix), `frame MM:SS` = frame (linked), `R:<file>` = reference repo, `§x` = [Official Rules](https://github.com/microsoft/insidethegamehackathon/blob/9c6c99620b06b2b04dcf69a434cdf4d203d19eda/OFFICIAL%20RULES.md) (pinned 9c6c996), `B` = `../brief.md`. The Innovation Studio page returned 404 on 2026-10-20.

Caveat: Benz says he has no insight into judging ([58] [E]); whether he judges is unknown, so read him as Microsoft taste, not the rubric [I]. Microsoft selects the panel (§6); the Premier League assists with judging the final entries (§2 [E]).

## 1. Portrait of a winning entry

**First 20 s of video.** The real app is already running on a synthetic match: a moment happens, and an insight card says *why it matters* (not just that it happened), with live/grounded badges, before any slide. Benz opens his talk the same way, clicking a question in the live app at [03] and showing the answer with numbers and grounded badges (frame [04:15](../frames/04-15.jpg)), then mentioning the trace view [04] [E]. The rules ask for footage of the project working (§4.4 [E]), say judges may stop at 2:00 (§4.4 [E]), and score "does the video clearly communicate value" (§6.2 [E]). So the hook must land first [I].

**README, above the fold.** One-sentence pitch; the pipeline Ingest → Interpret → Explain → Render → Personalise (§4.1 [E]); a mermaid architecture diagram; a "how it works" list of 3 bullets (R:README.md pattern [E]); provenance of the synthetic data and attribution of any third-party material near the top ([24–25] [E]); a 3-command quick start; a live demo link; the video link; a docs table (R:README.md [E]).

**Live demo.** Judges must be able to reach it free of charge; a private site needs login credentials in the testing instructions (§4.8 [E]). The judge sees: a match clock, an event feed, insight cards that carry receipts (status, evidence ID per number, chart from tool data, "what this data can't tell you"; frame [40:50](../frames/40-50.jpg) [E]), a persona or language switch that changes depth rather than colour (B, §4.1 [E]), and a trace or agent-handoff view ([29–30] [E]).

| Criterion (20% each, §6.2 [E]) | What wins it | Evidence |
| --- | --- | --- |
| Technological implementation (first tie-break, §6.3 [E]) | Generated synthetic events; code owns numbers; tests, CI, IaC, keyless identity | §6.2; Benz [12, 14–17] [E]¹ |
| Agentic design & innovation | Distinct agent roles on shared state; model only explains; grounding validator; scope refusal | §6.2; B; Benz [13, 39–40] [E]² |
| Real-world impact | Named user, timed output, production path (cost, eval gate, filter, telemetry) | §6.2; Benz [39, 41] [E]³ |
| UX & presentation | Card UI with visible receipts; clear video under 2 minutes | §6.2; B; frames [E]⁴ |
| Category fit | One named category, its exact clauses evidenced in README and video | §4.2, §4.3 [E]⁵ |

¹ §6.2 "optimized synthetic data creation"; schema, seed and realism checks, deterministic numbers, tests on fixtures, Entra, Bicep (R:ARCHITECTURE.md). ² §6.2 "Agentic AI patterns"; B (orchestration, MCP), so MCP or A2A where it is real; the validator rejects any number the tools did not return; multi-agent beyond his single agent [I]. ³ §6.2 "deployed in a production environment?"; named users such as a broadcaster, streaming app, or casual fan versus analyst; machine-readable output; Benz shows tokens and cost [39], an eval gate [41], content filter (slides, R:ONSTAGE §7). ⁴ Frontend and backend in balance (B); frame [39:30](../frames/39-30.jpg), frame [40:50](../frames/40-50.jpg). ⁵ §4.2 categories: overall, Foundry, enterprise, multi-agent, cloud-native. Clauses: enterprise (adoption path, reliability, transparency, controls), multi-agent (distinct roles, shared state, failure recovery), cloud-native (event-driven, automation, operational excellence); judges may reassign the category (§4.3).

## 2. Must-haves, differentiators, nice-to-haves

**Must-haves** (missing one risks rejection under the submission and testing rules, §4.4, §4.8 [E], or failing the stage-one theme and technology check, §6.1 [E]; the §4.1 pipeline items are "should", read here as must-haves [I])
- Synthetic, football-realistic event data (passes, shots, tackles) (§4.1(v), §4.7 [E]).
- Events ingested "as they happen", so a stream or replay clock is needed, not batch history (§4.1 [E]).
- All five pipeline stages visible, including Personalise (§4.1 [E]).
- A public GitHub repo, a public video under 2:00 on YouTube, Vimeo, Facebook Video or Youku, and an English elevator pitch (§4.4, §4.9 [E]).
- An unrestricted test build that works as shown in the video (§4.3, §4.8 [E]).
- Built after registration opened; licences honoured; no unlicensed PL marks, footage or music in the video (§4.3, §4.4, §4.6 [E]).
- Real use of the hackathon's technologies (§6.1 [E]). Foundry plus Azure services is the safest reading: Foundry is a hero technology (§6.2) and a category (§4.2), and Benz said “running on Azure is the goal” [61] [I]. Agent Framework is optional.

**Differentiators** (where points move [I])
- Grounded explanations with evidence IDs plus "what this can't tell you" (Benz's signature pattern, frame [40:50](../frames/40-50.jpg) [E]). Matching it is table stakes; beating it (evidence bound to each number) is the differentiator.
- The same moment framed for different audiences (casual versus analyst, favourite club or player) (§4.1, B [E]).
- Explainability beyond the scoreline: control versus chaos, rhythm, pressure (§4.1 [E]).
- Multi-agent collaboration with visible handoffs, shared state and recovery (§4.2 [E]).
- An evaluation suite that decides which model serves; per-answer cost and latency ([41] [E]).
- End-to-end traces, OpenTelemetry and App Insights ([29–30] [E]).

**Nice-to-haves**
- Suggested features: player ID tags, pass quality, ball and shot speed, auto-eventing from video (§4.1(ii) [E]; not each mandatory, B [E]).
- Multilingual stories (§4.1 [E]).
- Two-platform parity (AKS plus ACA), revisions and rollback ([31–38] [E]). This is mostly a cloud-native-category asset [I].
- A Copilot build story and a reusable generation prompt ([42–56] [E]).

## 3. Anti-patterns that lose

- **Real or scraped data as the core.** The rules require synthetic data (§4.7 [E]). Benz himself could not say whether Kaggle data is allowed ([16, 61] [E]).
- **A history Q&A chatbot.** It misses "as they happen", Render and Personalise (§4.1 [E]). His own app refuses a Premier League question ([28–29] [E]).
- **An IP allow-listed demo, or a login with no credentials in the testing instructions.** It breaks §4.8 [E]. Benz's endpoints admit only his IP ([14, 36, 52] [E]).
- **Numbers that come from the LLM.** Benz: "the model is not the source of the numbers" ([47] [E]). Ungrounded stats invite a hallucination critique [I].
- **A video that opens on slides or architecture, or runs past 2:00.** Judges may stop watching (§4.4 [E]).
- **Feature-list breadth without depth.** Suggestions are "just suggestions" ([01] [E]); B: suggested features are not each mandatory [E]; feature count earns no points in our own review scales (B), and the rules give no bonus for it [I].
- **Data committed without provenance, or no attribution.** Benz stresses credit ([11–12, 24] [E]).
- **Claiming planned work as working.** The project must function as depicted (§4.3 [E]).
- **Unnamed category, or category clauses not evidenced** (§6.2 category adherence [E]).
- **Premier League trademarks, footage or copyrighted music in the video** (§4.4 [E]).

## 4. Where Benz's demo is weak against the brief

| Gap | Verdict | Evidence |
| --- | --- | --- |
| Real versus synthetic data | **Confirmed.** Core data is real Kaggle CC0 results (1872–2026) plus World Bank data. Synthetic data appears only in test fixtures | R:README.md, R:data/README.md, [05, 12, 21] [E] |
| No live match events | **Confirmed.** Results only, no events. The data is static ("not changing that much"). The app states it has no match events | [06, 29]; R:ONSTAGE-SCRIPT L77 [E] |
| No Premier League or club football | **Confirmed.** "Premier League inspired scenarios are out of scope" | [28–29, 46] [E] |
| No personalisation | **Confirmed.** Questions are ephemeral, conversation storage is off, and grep found no persona or favourite code | [14] [E]; grep of R [I] |
| Single agent | **Confirmed.** One "insights agent", one Foundry model loop with 9 read-only tools, at most 6 tool calls. Multi-agent work appears only at build time (Copilot) | R:ARCHITECTURE.md, [14] [E] |
| No MCP or A2A | **Confirmed by absence.** Grep found no "mcp" in R | [I] |
| Not multilingual | **Confirmed by absence.** No locale or translation code | grep of R [I] |
| No Render for broadcast or timed output; no recaps or real-time narrative | **Confirmed.** Only a web Q&A and cards | R:ARCHITECTURE.md [E]; §4.1 asks for broadcast/streaming render [E] |
| No suggested features (player ID, pass quality, speed, video) | **Confirmed.** The data cannot support them | R:HACKATHON-GUIDE "tactics, player tracking need other data" [E] |
| Restricted access | **Confirmed.** IP allow-list plus Entra. As a submission it would fail §4.8 | [14, 36, 55–56] [E] |
| Over 2-minute storytelling | A 60-minute run of show, no short cut | R:ONSTAGE-SCRIPT [E]; irrelevant to him, critical for entrants [I] |

**Strengths a winner should match:** see [reference-repo.md §6](reference-repo.md#6-worth-copying-vs-demo-specific).

## 5. Video skeleton (under 1:55, his order compressed)

His order is live app with grounded answer and trace [03–04] → architecture and keyless security [09–20] → data honesty and a live refusal [20–30] → AKS vs ACA trade-offs [31–37] → receipts slide and evals [38–41] → Copilot build story [42–56] → three-line closing slogan (frame [57:32](../frames/57-32.jpg) [E]).

| Time | Screen | Voice (sketch) |
| --- | --- | --- |
| 0:00–0:15 | Live app, synthetic match at minute N; an event lands; a card explains why it matters | "A press won the ball at minute 63. Here is why it changed the game." |
| 0:15–0:35 | Switch audience or language; the same moment at casual versus analyst depth | "Same event, two fans, two explanations." |
| 0:35–0:55 | Receipts: grounded badge, evidence IDs, "can't tell", cost and latency | "Code computes every number; the model only explains, and a validator checks it." |
| 0:55–1:15 | Agent and trace view: roles, handoffs, a recovery | "Agents with distinct roles, shared state and recovery, on Foundry and Agent Framework." |
| 1:15–1:35 | One architecture slide: synthetic generator → event stream → agents → render | "Synthetic events, streamed like a real match, on Azure." |
| 1:35–1:50 | Category clause evidence (Foundry, enterprise, multi-agent or cloud-native), repo and live link | "Built for <category>: <two proof points>." |
| 1:50–1:55 | Slogan card plus URL/QR | Three short lines in the style of "Deterministic code for the numbers. A model for the words." |

Only working footage, no PL marks, no copyrighted music (§4.4 [E]).

## 6. Pre-submission checklist

1. The video is under 2:00, public on YouTube or Vimeo, and opens on the working product.
2. Every scene in the video is reproducible in the live build (§4.3).
3. The demo URL works from a fresh browser on an unknown IP; any login uses credentials given in the testing instructions (§4.8).
4. The repo is public, the README links the video and demo, and there is an English elevator pitch.
5. The README states the category and maps each clause to evidence.
6. All 5 pipeline stages are visible in the demo and named in the README.
7. Data is synthetic, labelled as such, with generator, seed, schema and realism checks documented.
8. Events are ingested live or on a replay clock ("as they happen").
9. Personalisation changes explanation depth, visibly.
10. Every number on screen traces to deterministic code; a grounding check is enforced.
11. Every insight explains *why*, with caveats and "can't tell".
12. Agent roles, handoffs and failure recovery are shown (required for the multi-agent category).
13. Foundry and Azure services are used for real, with keyless identity, and the IaC is in the repo.
14. Telemetry or a trace view, an eval suite, and per-answer cost and latency.
15. Tests and CI are green; the quick start works from a clean clone.
16. Attribution and licences are listed; no unlicensed PL marks, footage or music.
17. No secrets in git history; credentials are ignored.
18. Planned versus working is labelled honestly.
19. The live build stays up, free and unrestricted, until judging ends 10 Nov 11:59 PM PT (11 Nov Brisbane) (§1, §4.8).
20. Submit before 27 Oct 11:59 PM PT, with a dry run a day earlier.
