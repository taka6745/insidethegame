"""Grounding checks for the analyst's reply and the author's excerpt (docs/components/analysis.md §1, §3).
Never a pattern or phrase list: cited values must match served rows, text may use only numbers and names shown,
and unsupported claims are bounded questions for the decision model. Limits come from the storyline policy."""
import json
import re

from narrative_engine.context.render import score
from narrative_engine.decisions import Noul

# Invariants (the reply schema and the language checks); every tunable comes from the storyline policy
# (analysis.policy, `rules` below = its `analysis` section).
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
BANNED = re.compile(r"\b(xg|expected goals)\b", re.I)
PER_90 = re.compile(r"\bper 90\b|/90\b", re.I)  # trend rates are per 5 minutes; nothing is served per 90
LABEL_CHARS = re.compile(r"^[^\[\]\n\"]+$")
MARKS = {5.0, 10.0, 15.0, 45.0, 90.0}  # the trend windows' lengths and the halves': always citable minutes


def parse(text):
    """The JSON object in a reply (tolerating fences and prose around it), or None."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        reply = json.loads(match.group(0))
    except ValueError:
        return None
    return reply if isinstance(reply, dict) else None


def ledger_facts(ledger, info):
    """Key-event numbers the analyst may cite like trend rows: goals and red cards per team (match)."""
    goals = score(ledger, info)
    rows = []
    for team in (info.home, info.away):
        reds = sum(r["keyType"] == "RedCard" and r["contestantId"] == team.id for r in ledger)
        rows += [{"indicator": "goals", "label": "goals", "contestantId": team.id, "window": "match",
                  "value": goals[team.id]},
                 {"indicator": "red_cards", "label": "red cards", "contestantId": team.id, "window": "match",
                  "value": reds}]
    return rows


def _variants(value):
    """Ways a number can be written: as given, rounded, and a 0-1 share as a percentage."""
    if value is None or isinstance(value, bool):
        return set()
    v = float(value)
    out = {round(v, 2), round(v, 1), float(round(v))}
    if 0 <= v <= 1:
        out |= {round(v * 100, 1), float(round(v * 100))}
    return out


def allowed_numbers(facts, clock, rules):
    allowed = set().union(*(_variants(f.get("value")) for f in facts), *(_variants(f.get("previous")) for f in facts))
    allowed |= {float(n) for n in range(0, rules["small_counts_up_to"] + 1)}  # "two spells", "one of three"
    allowed |= {float(n) for n in range(1, clock.timeMin + 2)} | MARKS  # minutes up to the clock
    return allowed


def team_ids(info):
    ids = {}
    for t in (info.home, info.away):
        for name in (t.id, t.name, t.code):
            ids[name.lower()] = t.id
    return ids


def _same(a, b, rules):
    return abs(float(a) - float(b)) <= max(rules["value_tolerance"], abs(float(b)) * rules["relative_tolerance"])


def _cited(item, facts):
    """The indicator id an evidence item names: the table shows labels (render_trend_table); an id still counts."""
    named = str(item.get("indicator", "")).strip().lower()
    return next((f["indicator"] for f in facts if named in (f["indicator"], str(f.get("label") or "").lower())), None)


def _fact(item, facts, names, rules):
    """The served row this evidence item cites, or None."""
    if not isinstance(item, dict) or not isinstance(item.get("value"), (int, float)) or isinstance(item["value"], bool):
        return None
    team = names.get(str(item.get("team", "")).strip().lower())
    if team is None:
        return None
    indicator = _cited(item, facts)
    return next((f for f in facts if f["indicator"] == indicator and f["window"] == item.get("window")
                 and f["contestantId"] == team and f["value"] is not None and _same(item["value"], f["value"], rules)), None)


def _mismatch(item, facts, names):
    """Why an evidence item matches no served row, for the repair turn."""
    if not isinstance(item, dict):
        return "an evidence item is an object"
    indicator = _cited(item, facts)
    if indicator is None:
        return f"indicator {item.get('indicator')!r} is not in the table; use the name before the colon: " \
               f"{', '.join(sorted({f.get('label') or f['indicator'] for f in facts}))}"
    team = names.get(str(item.get("team", "")).strip().lower())
    if team is None:
        return f"team {item.get('team')!r} is not a team code"
    rows = [f for f in facts if f["indicator"] == indicator and f["contestantId"] == team]
    if item.get("window") not in {f["window"] for f in rows}:
        return f"window {item.get('window')!r} has no such row; windows: {', '.join(sorted({f['window'] for f in rows}))}"
    if not isinstance(item.get("value"), (int, float)) or isinstance(item.get("value"), bool):
        return "value must be a number without units"
    shown = next(f["value"] for f in rows if f["window"] == item["window"])
    return f"the table shows {shown if shown is None else round(shown, 2)}"


def validate(reply, trends, ledger, storylines, info, clock, *, rules):
    """(accepted observations, accepted resolves, rejected [{item, reasons}]). `reply` is the parsed JSON
    (None when unparseable); `rules` the policy's `analysis` section. Accepted observations carry the served
    rows they cite (`facts`)."""
    if reply is None:
        return [], [], [{"item": None, "reasons": ["reply is not a JSON object"]}]
    open_lines = {s["id"]: s for s in storylines if s["status"] != "resolved"}
    facts = list(trends) + ledger_facts(ledger, info)
    names = team_ids(info)
    players = {name for pid, name in info.players.items() if any(r.get("playerId") == pid for r in ledger)}
    others = {name for name in info.players.values()} - players
    items, rejected = reply.get("observations"), []
    if not isinstance(items, list):
        items, rejected = [], [{"item": items, "reasons": ["observations is not a list"]}]
    accepted, moved, most = [], set(), rules["max_observations"]
    for item in items[:most]:
        reasons, cited = _check(item, facts, names, others, open_lines, clock, moved, info, rules)
        if reasons:
            rejected.append({"item": item, "reasons": reasons})
            continue
        if item.get("storyline") not in (None, "open"):
            moved.add(item["storyline"])
        accepted.append({**{k: item.get(k) for k in ("label", "headline", "explanation", "storyline")},
                         "confidence": _confidence(item.get("confidence"), rules),
                         "team": names.get(str(item.get("team") or "").lower()), "facts": cited})
    rejected += [{"item": i, "reasons": [f"more than {most} observations"]} for i in items[most:]]
    resolves = []
    for item in reply.get("resolve") or []:
        line = open_lines.get(item.get("storyline")) if isinstance(item, dict) else None
        if line is None or line["id"] in {r["storyline"] for r in resolves}:
            rejected.append({"item": item, "reasons": ["storyline is not open"]})
            continue
        reasons = _text(item.get("outcome"), allowed_numbers(facts, clock, rules), {line.get("team")} - {None},
                        names, others, rules["outcome_max_chars"], info)
        if reasons:
            rejected.append({"item": item, "reasons": reasons})
        else:
            resolves.append({"storyline": line["id"], "outcome": item["outcome"].strip()})
    return accepted, resolves, rejected


def _check(item, facts, names, others, open_lines, clock, moved, info, rules):
    if not isinstance(item, dict):
        return ["observation is not an object"], []
    reasons = []
    low, high = rules["label_chars"]
    label = item.get("label")
    if not isinstance(label, str) or not low <= len(label.strip()) <= high or not LABEL_CHARS.match(label.strip()):
        reasons.append(f"label must be {low}-{high} characters, no brackets, quotes or line breaks")
    team = item.get("team")
    team_id = names.get(str(team).lower()) if team is not None else None
    if team is not None and team_id is None:
        reasons.append(f"unknown team {team!r}")
    evidence = item.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= rules["max_evidence"]:
        listed = f" (it lists {len(evidence)})" if isinstance(evidence, list) else ""
        reasons.append(f"evidence must list 1-{rules['max_evidence']} items{listed}")
        evidence = []
    cited = []
    for e in evidence:
        fact = _fact(e, facts, names, rules)
        if fact is None:
            reasons.append(f"evidence does not match the served numbers: {e} ({_mismatch(e, facts, names)})")
        else:
            cited.append(fact)
    if team_id and cited and not any(f["contestantId"] == team_id for f in cited):
        reasons.append("evidence does not include the team the observation is about")
    confidence = _confidence(item.get("confidence"), rules)
    levels = rules["confidence_levels"]
    short = cited and all(f["window"] in rules["short_windows"] for f in cited)
    cap = rules["confidence_cap_short"] if short else rules["confidence_cap_long"]
    if confidence is None:
        reasons.append(f"confidence must be one of {', '.join(map(repr, levels))}")
    elif confidence > cap + 1e-9:
        fits = [name for name, value in levels.items() if value <= cap + 1e-9]
        windows = " or ".join(f'"{w}"' for w in rules["short_windows"])
        reasons.append(f"confidence {item['confidence']!r} is above the cap for evidence only from window {windows} "
                       f"(use {' or '.join(map(repr, fits))}, or also cite a longer window)" if short
                       else f"confidence {item['confidence']!r} is above the cap {cap}")
    teams = {f["contestantId"] for f in cited}
    allowed = allowed_numbers(cited, clock, rules)
    for field, limit in (("headline", rules["headline_max_chars"]), ("explanation", rules["explanation_max_chars"])):
        if field == "headline" or item.get(field) is not None:
            reasons += _text(item.get(field), allowed, teams, names, others, limit, info, field)
    move = item.get("storyline")
    if move not in (None, "open"):
        line = open_lines.get(move)
        if line is None:
            reasons.append(f"storyline {move!r} is not open")
        elif move in moved:
            reasons.append(f"storyline {move} already moved by another observation in this analysis (set storyline "
                           f"to null, or merge the two observations)")
    return reasons, cited


def _text(text, allowed, teams, names, others, limit, info, field="outcome"):
    if not isinstance(text, str) or not text.strip() or len(text) > limit:
        return [f"{field} must be 1-{limit} characters"]
    reasons = []
    if bad := [n for n in NUMBER.findall(text) if float(n) not in allowed]:
        reasons.append(f"{field} uses numbers not in its evidence: {', '.join(bad)} (cite the row each number "
                       f"comes from, or leave the number out)")
    for team in (info.home, info.away):
        named = re.search(rf"\b({'|'.join(map(re.escape, team.names))})\b", text)
        if named and team.id not in teams:
            reasons.append(f"{field} names {team.name}, which its evidence does not cover (cite a {team.code} "
                           f"row too, or leave {team.name} out)")
    if bad := [p for p in others if re.search(rf"\b{re.escape(p)}\b", text)]:
        reasons.append(f"{field} names players not in the key events: {', '.join(sorted(bad))}")
    return reasons + _wording(text, field)


def _wording(text, field):
    reasons = []
    if BANNED.search(text):
        reasons.append(f"{field} uses a statistic the data does not have (xG)")
    if PER_90.search(text):
        reasons.append(f"{field} gives a rate per 90 minutes; the trend rates are per 5 minutes")
    return reasons


def _either(words):
    quoted = [f'"{w}"' for w in words]
    return " or ".join([", ".join(quoted[:-1]), quoted[-1]] if len(quoted) > 2 else quoted) or "none"


def prompt_limits(rules):
    """match-analyst v3+'s limit placeholders, from the same `analysis` rules this module checks against."""
    levels = sorted(rules["confidence_levels"].items(), key=lambda kv: kv[1])
    under = lambda cap: [name for name, value in levels if value <= cap + 1e-9]
    return {"max_observations": rules["max_observations"], "max_evidence": rules["max_evidence"],
            "confidence_levels": _either(under(rules["confidence_cap_long"])),
            "short_windows": _either(rules["short_windows"]),
            "short_window_levels": _either(under(rules["confidence_cap_short"]))}


def _confidence(value, rules):
    """A confidence level (match-analyst v2+) or a v1 number from 0 to 1, as a number; None if invalid."""
    if isinstance(value, str):
        return rules["confidence_levels"].get(value.strip().lower())
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
        return float(value)
    return None


def repairable(rejected):
    """Rejections worth one repair turn: all but observations beyond the limit."""
    return [r for r in rejected if not any(x.startswith("more than") for x in r["reasons"])]


def repair_request(rejected):
    """The follow-up message listing each rejected item with its reasons."""
    lines = []
    for r in repairable(rejected):
        item = r["item"]
        if isinstance(item, dict) and "outcome" in item and "headline" not in item:
            what = f"resolve of {item.get('storyline')}"
        elif isinstance(item, dict):
            what = f"observation \"{item.get('label')}\""
        else:
            what = "your reply"
        lines.append(f"- {what}: {'; '.join(r['reasons'])}")
    return ("The grounding check rejected these items:\n" + "\n".join(lines) + "\n\nReply with only the JSON object "
            "in the same format, holding a corrected version of each rejected item and nothing else (the other "
            "items stand). Fix each by changing the text or the evidence to match the trend table; leave an item "
            "out if the table does not support it.")


def merge(reply, rejected, repair, rules):
    """The first reply's accepted items followed by the repair's items (at most one per rejected item), to be
    validated again as one reply, so the storyline-move and resolve limits hold across both."""
    if not isinstance(reply, dict):
        return repair
    repair = repair if isinstance(repair, dict) else {}
    listed = lambda doc, key: doc.get(key) if isinstance(doc.get(key), list) else []
    dropped = [r["item"] for r in repairable(rejected)]
    failed = lambda item: any(item is d for d in dropped)
    first = listed(reply, "observations")[:rules["max_observations"]]
    resolve = listed(reply, "resolve")
    return {"observations": [i for i in first if not failed(i)]
            + listed(repair, "observations")[:sum(map(failed, first))],
            "resolve": [i for i in resolve if not failed(i)] + listed(repair, "resolve")[:sum(map(failed, resolve))]}


SERVED = ("game_state_statistics", "match_trends", "storylines", "key_event_ledger", "match_events", "trigger_reason",
          "story_so_far")
WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19, "twenty": 20}
NUMBER_WORD = re.compile(rf"\b({'|'.join(WORDS)})\b", re.I)
CAPITALISED = re.compile(r"(?<![\w'’])([^\W\d_][\w'’.-]*)")
SENTENCE_END = re.compile(r"[.!?:;—–]\s*$|^\W*$")


def _served_numbers(variables, clock, rules):
    found = set()
    for key in SERVED:
        for n in NUMBER.findall(str(variables.get(key) or "")):
            found |= _variants(float(n))
    found |= {float(n) for n in range(0, rules["small_counts_up_to"] + 1)}
    found |= {float(n) for n in range(1, clock.timeMin + 2)} | MARKS
    return found


def _vocabulary(variables, info):
    """Capitalised words the author may use: the roster, the teams (with their MA1 short and known names), and
    any word shown in its inputs."""
    words = set()
    for text in [*info.players.values(), *info.home.names, *info.away.names, *(str(v) for v in variables.values())]:
        words |= {re.sub(r"['’]s$", "", w.lower().strip("'’.")) for w in re.split(r"[\s/()\[\],;:\"!?]+", text)}
    return words | {"var"}


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def trim_unsupported(text, reasons):
    """`text` without the sentences its claim reasons quote, or None when a reason is not about one sentence
    (numbers, names, wording) or nothing would be left. Every other sentence passed its own claim questions."""
    sentences = _sentences(text)
    failing = {s for s in sentences if any(r.endswith(f'"{s.strip()}"') for r in reasons)}
    if not failing or any(not any(r.endswith(f'"{s.strip()}"') for s in failing) for r in reasons):
        return None
    kept = [s for s in sentences if s not in failing]
    return " ".join(kept) or None


def narrative_reasons(text, variables, info, clock, *, rules):
    """Why an author excerpt is not grounded in what the author was shown (empty if it is): numbers must be
    in the statistics, trends, storylines, ledger, events, trigger or the followed story so far (or small
    counts and minutes); names in the roster, the teams or the inputs; no xG or per-90 rates. Causal, intent and
    result claims: `claim_reasons`."""
    if not isinstance(text, str) or not text.strip():
        return ["the excerpt is empty"]
    reasons = []
    allowed = _served_numbers(variables, clock, rules)
    numbers = NUMBER.findall(text) + [str(WORDS[w.lower()]) for w in NUMBER_WORD.findall(text)]
    if bad := sorted({n for n in numbers if float(n) not in allowed}, key=float):
        reasons.append(f"uses numbers not shown in the statistics, trends or storylines: {', '.join(bad)} "
                       f"(quote numbers as shown; do not calculate new ones)")
    vocabulary, unknown = _vocabulary(variables, info), []
    for match in CAPITALISED.finditer(text):
        word = re.sub(r"['’]s$", "", match.group(1).rstrip("'’."))
        if not word[0].isupper() or SENTENCE_END.search(text[:match.start()]):
            continue
        if word.lower() not in vocabulary:
            unknown.append(word)
    if unknown:
        reasons.append(f"names {', '.join(dict.fromkeys(unknown))}, which are not in the roster or the data")
    return reasons + _wording(text, "the excerpt")


def claim_state(variables):
    """The evidence a claim may rest on: every factual input the writer saw (storylines with their beats, the key
    event ledger, the trends, the statistics table, the minute recaps, the latest events) and the trigger. A
    comparison or cause drawn from the statistics or recaps is checked against them, not against a subset."""
    always = (("The match's storylines (with their beats)", "storylines"), ("The key event ledger", "key_event_ledger"),
              ("The match trends", "match_trends"))
    shown = (("The match statistics", "game_state_statistics"), ("The minute recaps so far", "combined_match_context"),
             ("The latest events", "match_events"))
    return "\n\n".join([f"{title}:\n{variables.get(key) or 'None.'}" for title, key in always]
                       + [f"{title}:\n{variables[key]}" for title, key in shown if variables.get(key)]
                       + [f"This step was triggered by:\n{variables.get('trigger_reason') or 'None.'}"])


async def claim_reasons(text, variables, decisions, claims):
    """Sentences making a claim (a cause, an intent, the result) the evidence does not support, asked of the decision model in
    one batch, each with the sentence before it for its pronouns: per sentence and enabled claim, `claim` (does it make this kind of claim?) and `support` (does
    the evidence state it?). A sentence fails when P(claim) ≥ min_claim_probability and P(support) <
    min_support_probability; a declined answer counts as no. `claims`: the policy's `claims` section."""
    return (await claim_reasons_many([(text, variables)], decisions, claims))[0]


async def claim_reasons_many(items, decisions, claims):
    """`claim_reasons` for several (text, variables) at once: one decision call per distinct evidence state
    (every bucket of one step shares it), keys prefixed per item (`e{n}s{i}_{claim}`)."""
    checks = {name: c for name, c in claims.items() if c["enabled"]}
    groups, sentences = {}, []
    for n, (text, variables) in enumerate(items):
        sentences.append([s.strip() for s in _sentences(text or "")])
        if checks and sentences[-1]:
            groups.setdefault(claim_state(variables), []).append(n)
    answers = {}
    for state, members in groups.items():
        asked = {}
        for n in members:
            for i, sentence in enumerate(sentences[n], 1):
                # The sentence before it resolves "they", "it" and "that" to what the writer meant.
                after = f" (it follows: \"{sentences[n][i - 2]}\")" if i > 1 else ""
                for name, c in checks.items():
                    asked[f"e{n}s{i}_{name}"] = Noul(f"The sentence: \"{sentence}\"{after}\n{c['claim']}")
                    asked[f"e{n}s{i}_{name}_support"] = Noul(f"The sentence: \"{sentence}\"{after}\n{c['support']}")
        answers |= (await decisions.decide(state, asked)).answers
    p = lambda key: answers[key].probability if key in answers else 0.0
    return [[f"{c['repair']}: \"{sentence}\"" for i, sentence in enumerate(sentences[n], 1)
             for name, c in checks.items()
             if p(f"e{n}s{i}_{name}") >= c["min_claim_probability"]
             and p(f"e{n}s{i}_{name}_support") < c["min_support_probability"]] for n in range(len(items))]


async def analyst_claim_rejections(reply, accepted, resolves, rejected, variables, decisions, claims, cache=None):
    """(accepted, resolves, rejected) after the claims marked `analyst`: each accepted observation (label, headline
    and explanation: a label becomes the storyline's name) and resolve (outcome) is asked against the analyst's
    inputs as the evidence state; one that
    fails moves to `rejected` as its reply item, so the repair turn and `merge` treat it like any rejection.
    `cache` ({text: reasons}, one analysis) keeps an item that passed once from being asked again after a repair."""
    checks = {name: c for name, c in claims.items() if c["enabled"] and c["analyst"]}
    if not checks or decisions is None or not (accepted or resolves):
        return accepted, resolves, rejected
    dropped = [r["item"] for r in rejected]
    kept = lambda key: [i for i in reply.get(key) or [] if not any(i is d for d in dropped)]  # validate's order
    observation_items, resolve_items = kept("observations"), kept("resolve")
    state = {**variables, "trigger_reason": variables.get("analysis_reason")}
    texts = [". ".join(filter(None, (o.get("label"), o.get("headline"), o.get("explanation")))) for o in accepted]
    texts += [r["outcome"] for r in resolves]
    cache = {} if cache is None else cache
    new = list(dict.fromkeys(t for t in texts if t not in cache))
    cache |= dict(zip(new, await claim_reasons_many([(t, state) for t in new], decisions, checks)))
    found = [cache[t] for t in texts]
    out_obs, out_res, out_rej = [], [], list(rejected)
    for i, (accepted_item, reasons) in enumerate(zip(accepted + resolves, found)):
        is_obs = i < len(accepted)
        item = observation_items[i] if is_obs else resolve_items[i - len(accepted)]
        if reasons:
            out_rej.append({"item": item, "reasons": reasons})
        else:
            (out_obs if is_obs else out_res).append(accepted_item)
    return out_obs, out_res, out_rej


def narrative_repair_request(reasons):
    return ("A grounding check rejected the excerpt:\n" + "\n".join(f"- {r}" for r in reasons) +
            "\n\nWrite the excerpt again, fixing these, as plain text only.")
