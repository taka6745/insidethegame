# Judge lens: Brian Benz, the Reactor livestream (uploaded 15 Oct 2026; runbook date 14 Oct, 9–10 AM PT)

Source: `transcript/transcript.txt` (auto captions, one-minute buckets; `[46]` means video minute 46, the caption prefix, not the file line), `transcript/metadata.json`, `frames/` (`frame MM:SS`; frame times drift slightly from caption minutes), `../brief.md`. Quotes are lightly cleaned of filler words. Counts are rough grep counts plus a manual read.

Caveat on the premise: he says "I'm just the guy who built the demo" and has "none whatsoever" on judging [58]. Nothing shows he is a judge. Read this as "what a Microsoft AI/cloud advocate rewards", which is the likely panel profile (brief: "Microsoft selects the panel").

## 1. Values he repeats

| Value | Rough freq | Evidence |
| --- | --- | --- |
| **Data attribution / provenance / licence**: his most emotional theme, 5 separate moments | ~15 | "make sure that Mart [Jürisoo, the dataset author] gets full credit" (captions say "Mark") [12, 24, 25, 42, 49] |
| **Code does the numbers, model does the words**: the closing slide's thesis | ~8 | "the model is not the source of the numbers" [12, 47]; frame [13:15](../frames/13-15.jpg), frame [57:32](../frames/57-32.jpg) |
| **Grounding / anti-hallucination** ("ground", "hallucinat") | ~12 + 3 | "an evidence ID for every number" [39, 40]; frame [13:15](../frames/13-15.jpg) |
| **Honesty about limits / scope refusal** | ~10 | "what this data can't tell you" [13, 29, 40] |
| **Security / identity** (Entra/identity, "secur", allow list) | ~18 + 9 + 6 | "limited by IP and my own Entra ID" [14, 15, 17, 52]; frame [12:30](../frames/12-30.jpg) |
| **Observability / traces** | ~10 | "a trace view that shows you how everything actually happened" [04, 29–30]; frame [40:25](../frames/40-25.jpg), frame [58:29](../frames/58-29.jpg) |
| **Cost / latency / model choice** | ~8 | "the sweet spot between quality results and speed" [07, 14, 39, 41, 47] |
| **Copilot productivity / AI-built code** ("Copilot") | ~17 | "I'm not writing a lot of hand code these days" [08–09, 42–44] |
| **Simplicity / pragmatism** ("easy/simple/quick") | ~17 | "just easier to use when you're working with the AI" [10–11, 33, 50] |
| **Reproducibility / reuse** | ~5 | "one set of images, three services, two platforms" [09, 20, 54]; frame [57:32](../frames/57-32.jpg) |

## 2. Hints about a good entry

### Explicit (he said it)
- **Focus on the app, not the dataset.** "The focus is not really on the data itself, but really on the application and how you're actually visualizing things" [23]. *High confidence.*
- **Relate it to the Premier League.** "Obviously it should have something to do with Premier League" [23]. *High.*
- **Synthetic data is fine and easy.** "Make up your own leagues… synthetic made-up data is probably the easiest to do these days" [21]. *High that he approves; he cannot speak for the rules.*
- **Build locally first.** No credits are provided: "That's one good reason to build it locally before you deploy it to Azure" [57]. *High.*
- **Running on Azure is the point.** "Really running on Azure is the goal" [61]. *High.*
- **Any programming language is fine.** "Although you can use any language you want" [47], meaning programming language (said of Python). Separately, submission materials must be in English or include an English translation (rules §4.9). *High.*

### Inferred (reading between the lines)
- **Show receipts on screen**: evidence IDs, "grounded N numbers checked", latency, tokens and cost per answer. This was his "OPERATE" slide [38–40], and it is the most demo-able form of trust. *High.*
- **Show your AI-assisted build.** He spent minutes 42–56 on the prompt and iterations. *Medium–high.*
- **Credit sources in the product and the README, not only in the licence file.** "Right on the front page… right after the description" [24]. A visible data-provenance label for synthetic data probably scores the same way. *High.*
- **A graceful "I can't answer that" is a feature to demo.** He deliberately asked an out-of-scope question live [28–29]. *High.*
- **Keep the model out of arithmetic.** It is his closing thesis, so expect Microsoft judges to probe "where do the numbers come from?". *High.*
- **Justify each platform choice in one line** ("AKS for full lifecycle, ACA for disposable dev/test") rather than listing services [33–37]. *Medium.*
- **Name model trade-offs, and measure them.** He said Astra "was too slow… the results were the same as GPT-6 Sol" [47], but his repo never compared the two (see reference-repo §5). Measured, dated evidence would beat his claim. *Medium.*
- **Least privilege on tools**: "No write, admin, shell, SQL, or network tools" (frame [13:15](../frames/13-15.jpg)). An agent with broad powers may worry him. *Medium.*
- **He likes bounded agents more than sprawling ones**: max six tool calls, one retry, ephemeral, "not really a chatbot" [14]. The multi-agent category may need a clear reason for each agent. *Medium–low; he never discussed multi-agent.*
- **He did not discuss personalisation, multilingual output, live events or video**, beyond showing the official hackathon slide (frame [04:43](../frames/04-43.jpg)). He shows no bias on the brief's suggested features. Nothing suggests he penalises their absence. *Medium.*

## 3. How he explains things

- **Structure**: hook with the hackathon and prize → live demo first [03–05] → data origin [05–08] → agenda [08] → architecture → security → portal tour → data → AKS vs ACA → receipts/observability → Copilot prompt → Q&A. He goes **demo → why it's trustworthy → how it was built**.
- **Demo-first, with a real question.** He clicks a pre-built question ("Did hosting help Canada, Mexico and the US") and reads out concrete numbers: "Mexico seems to be the big winner, 0.3 [points per match above expectation]" [03–04].
- **Slogans as anchors**: "Code computes. The model explains."; "Every answer carries its receipts"; "One set of images, three services, two platforms"; "Same intent, different shapes" [32].
- **Trade-offs**: he picks by use case, not winner. "We're not supposed to compare them, but I did anyway" [08]; "I'm not really recommending one or the other. It's just whatever you need" [35]. Each option gets one plain line: ACA = "disposable… dev test", AKS = "full life cycle management" [33–34]. He counts effort ("24 declarations, 535 lines" for AKS [32–33]).
- **He admits flaws in public** and it doesn't cost him credibility: "These arrows are actually wrong" [19]; "a bit misleading" [20]; the allow list "is a pain for me" [52].
- **Language he likes**: grounded, evidence, receipts, credit, public domain, deterministic, secure, sweet spot, disposable, inspiration, real-world.
- **Language he avoids**: superlatives about AI accuracy (he corrects himself to "minimizes hallucinations" [40]), platform tribalism ("not here to promote one platform" [60]), AWS comparisons [60–61].
- **Pacing problems**: he ran out of time ("6 minutes left" [53], "2 minutes over" [61]); he skipped his planned live Copilot "add question 8" demo (slide 20) for time [38] and the Copilot UI misbehaved [44, 54]. He values a scripted run of show ("60-minute run of show" [51]).

Video plan: see [winner-profile.md §5](winner-profile.md#5-video-skeleton-under-155-his-order-compressed) (canonical).

## 4. Q&A

| Time | Question | His answer | Read |
| --- | --- | --- | --- |
| [15] | Can we use Premier League data, or synthetic only, for match commentary? | Calls the Kaggle dataset "an MIT license" (it is actually CC0) and says he doesn't redistribute it. Never answers the PL-data part. | **Dodge** (deflected to his own dataset) |
| [16–17] | The hackathon says synthetic data is required. Is open Kaggle data OK? | "I don't have the ins and outs of the rules… they're asking for synthetic data because they don't want to have any liability issues… [whoever runs] the hackathon rules will have to manage. I don't know." | **Dodge** (second time), but he offers the liability rationale |
| [20–21] | Can we create our own synthetic data and schema, or use a specific dataset? | "I'd recommend doing what I did here… finding… open source data that is public domain… you can create synthetic data from that or… just generate synthetic data… make up your own leagues… synthetic made-up data is probably the easiest." | Yes to synthetic, but he first recommends public-domain real data as a source; the rules (§4.7) still require synthetic data |
| [22] | Is it beginner-friendly? | "Available to any abilities… Copilot helps." | Generic |
| [57–58] | Do we need our own credits? | "No, unfortunately not… build it locally before you deploy it to Azure… no credits provided." | Straight answer: **no credits** |
| [58] | Any insights about judging? | "None whatsoever… I'm just the guy who built the demo." | **Dodge / disclaimer** |
| [58] | How do we submit? | Register by the 20th, submit by the 27th, "I assume there's some instructions on there." | Vague |
| [59] | How long did it take? | "About a day… Copilot really helped." | Answered |
| [59–60] | Copilot vs Codex vs Claude Code? | "That's up to you… not here to promote one platform", then promotes Copilot's model choice. | Soft sell |
| [60–61] | Is Azure very different from AWS? | "That's a whole different presentation." | **Dodge** |
| [61–62] | Synthetic data again | "The organizer[s] of the hackathon are the people to answer that. I'm not sure." | **Dodge** (third time) |
| [62] | "Share the prize with us" | "I'll submit this and see if I win" → "I'm not submitting this." | Joke; contradictory |

**What the dodges imply**
- The synthetic-data rule is unresolved from Microsoft's side. Treat the official rules as binding: §4.7 says "Projects must use synthetic, football-realistic data". Real data used as a seed or reference needs clear labelling and a synthetic layer for events.
- Since the judging criteria weren't discussed, the published 20% × 5 rubric is all there is. His personal values (above) are only a secondary lens; the official tie-break is the criterion scores in order, starting with Technological Implementation (§6.3).
- No credits means judges know entrants pay. A cheap, locally runnable demo with an explicit cost per answer fits that.

## 5. Tensions and contradictions

- **Synthetic required vs real data used.** Rules §4.7 require synthetic, football-realistic data; his reference app uses real Kaggle results and says "I just used the data that I found online" [16]. *Meaning*: his demo is not a compliant template. Copying its data approach risks stage-one rejection. Generate synthetic events and keep real data only as optional, attributed seed or reference.
- **Session description vs app scope.** The description promised "identifying team play styles, analyzing counterattacks, or uncovering player performance patterns" (metadata). His prompt says "Premier League inspired scenarios are out of scope" [46], and the app refuses "best Premier League team at counter attacks" [29]. *Meaning*: the gap he left (club, event-level, tactical insight) is exactly what the brief asks for. Entrants who deliver it fill the space his demo opened. He even named the data needed: "passes, shots, and player positions" [29].
- **"Premier League data" vs international data.** He calls it "Premier League data from Kaggle" [03] and "I just used the Premier League data" [21], but it is men's international results. *Meaning*: he is loose on football specifics and strict on engineering and provenance. Expect judging pressure on trust and architecture, not tactical accuracy (under rules §2, the Premier League assists with judging the final entries, so football accuracy may still count).
- **"Not promoting a platform" vs Microsoft stack expected.** "I'm not here to promote one platform" [60] vs "really running on Azure is the goal" [61] and the tool list "GitHub Copilot, Microsoft Foundry, Azure AI services, Fabric…" [01]. *Meaning*: non-Microsoft tools are tolerated in the dev workflow, but the runtime should visibly run on Azure/Foundry.
- **"Not supposed to compare AKS/ACA" vs a comparison slide** [08, 35]. *Meaning*: a candid trade-off is welcome even when it's off-message.
- **Will he enter?** "I might enter it myself" [01] vs "I'll submit this and see if I win" vs "I'm not submitting this" [62]. Also titled "Principal AI Advocate" on screen but "Principal Cloud Advocate" on the title card (frame [00:03](../frames/00-03.jpg)). *Meaning*: casual and unscripted. Don't over-read his statements as official.
- **"Secure" vs blocking judges.** The IP allow list means "no one else can do it, just me" [36]. Rules §4.8 require free, unrestricted access for judges until judging ends (a private site must give login credentials). *Meaning*: his security posture would fail the access requirement. Entrants need public or judge-accessible endpoints with other controls.
- **Synthetic data shows up only in tests.** "Tests that we built on synthetic data" [12], yet synthetic data is not his data source. *Meaning*: he sees synthetic data as a testing tool, so a well-designed synthetic generator with a documented schema is a credible "technical quality" story he would recognise.

## 6. Red flags he'd likely mark down

See also [winner-profile §3](winner-profile.md#3-anti-patterns-that-lose).

- **Numbers written by the LLM** with no traceable source or check. This contradicts his closing thesis.
- **No data attribution or provenance**, or real/scraped data passed off as your own or as synthetic: "I don't want to be obfuscating… make it look like it came from me" [12].
- **Real Premier League data or footage** with unclear rights. He flagged liability as the reason for the synthetic rule [16].
- **Confident answers to questions the data can't support**, with no refusal path. He demoed the opposite on purpose [29].
- **Committed secrets or key-based auth**: he stressed keyless, managed identity and short-lived tokens [14–17].
- **Agents with unbounded tools or loops** and no limits on latency or cost [14].
- **Opaque runtime**: no traces, no latency or cost visibility [04, 30, 39].
- **Over-claiming**: "no hallucinations" or "production-ready" without evidence. He corrected himself publicly [40].
- **A demo that isn't on Azure, or can't be reached by judges** [61].
- **Data bundled in the repo without licence clarity** [12, 26, 49].
- **An unfocused video** that runs over time or spends it on infrastructure plumbing instead of the user-facing answer.
