# Narrative prompt seeds

The seed of each role in the backend prompt store (`narrative_prompts`), copied byte for byte from the narrative engine so the backend never reads another service's folder at runtime:

| Seed | Source |
| --- | --- |
| `minute-summary.txt` | `narrative-engine/narrative_engine/agents/prompts/minute-summary.v3.txt` (v2 + neutral example teams) |
| `context-compression.txt` | `narrative-engine/narrative_engine/agents/prompts/context-compression.v2.txt` (v1 + neutral example teams) |
| `match-analyst.txt` | `narrative-engine/narrative_engine/agents/prompts/match-analyst.v4.txt` (v3 + labels and headlines in plain words, from what each indicator measures) |
| `match-analyst.v3.txt` | `match-analyst.v3.txt` (v2 with its limits as placeholders filled from the storyline policy), which `029` adds |
| `match-analyst.v2.txt` | `match-analyst.v2.txt` (v1 with the side-by-side trend table and confidence levels), which `025` adds |
| `narrative-author.txt` | `narrative-engine/narrative_engine/agents/prompts/narrative-author.v6.txt` (v5 + trend units, no example excerpt) |
| `match-analyst.v1.txt` | `match-analyst.v1.txt` (storylines: observations citing trend numbers), which `023` adds |
| `narrative-author.v5.txt` | `narrative-author.v5.txt` (v4 + `{storylines}`, `{match_trends}`), which `023` activates |
| `narrative-author.v4.txt` | `narrative-author.v4.txt` (v3 + SPADL glossary), which `021` adds |
| `subscription-decision.txt` | `narrative-engine/narrative_engine/agents/prompts/subscription-decision.v2.txt` (the state Decision-1 judges for story follows; no viewer text) |
| `subscription-decision.v1.txt` | `subscription-decision.v1.txt` (with the `{follows}` list), which `024` adds |
| `subscription-author.txt` | `narrative-engine/narrative_engine/agents/prompts/subscription-author.v1.txt` (a followed story's narrative) |
| `subscription-planner.txt` | This service's own role: the follow chat's planner (agents/subscription_planner.py) |

Each seed's `{name}` tokens fix that role's placeholder set; saved versions must keep exactly that set. A fresh store gets the seeds as version 1. [`021_spadl_prompts.py`](../021_spadl_prompts.py) adds the SPADL versions to an existing store and activates them only where the role still runs an unedited seed. [`023_storyline_prompts.py`](../023_storyline_prompts.py) adds `match-analyst` and makes author v5 active even over an edit (its placeholders changed, and the engine accepts only the shipped set); the edit stays as a version. [`025_grounded_prompts.py`](../025_grounded_prompts.py) adds analyst v2 and author v6 (same placeholders) and activates them only where the role still runs an unedited seed. [`024_subscriptions.py`](../024_subscriptions.py) adds the three subscription roles to an existing store. [`029_policy_prompts.py`](../029_policy_prompts.py) adds analyst v3 and subscription-decision v2 and, since both change their placeholders, makes them active even over an edit (kept as a version). [`030_grounded_patterns.py`](../030_grounded_patterns.py) adds analyst v4 (same placeholders) and activates it only where the role still runs an unedited seed. [`050_neutral_prompt_examples.py`](../050_neutral_prompt_examples.py) swaps the neutral examples into an active `minute-summary` or `context-compression` that still names real or demo clubs, keeping the rest of an edit. Later edits live in Postgres.
