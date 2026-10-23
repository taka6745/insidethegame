"""Storyline reducer and focus choice: pure functions of the previous storylines and one validated analysis.
Key events are linked by rule (`_link`), never by the model. Lifecycle: docs/components/analysis.md §2."""
import copy

FADED = "Closed: no later analysis developed it."  # says nothing about the match, so no excerpt cites it as a trend
# Every number here comes from the storyline policy's `storylines` section (`rules`), analysis.policy.


def clock_doc(clock, second=None):
    doc = {"periodId": clock.periodId, "timeMin": clock.timeMin, "label": clock.label}
    return doc if second is None else {**doc, "timeSec": second}


def norm(label):
    return " ".join(label.lower().split())


def concerns(line, key_row):
    """Is this storyline's team involved in the key event (a storyline about both teams always is)?
    An own goal concerns both sides."""
    return line["team"] is None or key_row["contestantId"] == line["team"] or key_row["keyType"] == "OwnGoal"


def reduce(previous, observations, resolves, ledger, *, match_id, analysis_id, clock, horizon, rules, final=False,
           final_outcome="Full time."):
    """The storylines after one analysis. `observations`/`resolves` come from validator.validate;
    `horizon` is [periodId, timeMin, second]; `ledger` holds the key events up to it."""
    lines = copy.deepcopy(previous)
    by_label = {norm(s["label"]): s for s in lines if s["status"] != "resolved"}
    at = clock_doc(clock)
    touched = set()
    for item in observations:
        move = item["storyline"]
        if move not in (None, "open"):
            line = next(s for s in lines if s["id"] == move)
        else:
            line = by_label.get(norm(item["label"])) or _reopened(lines, item["label"], clock, rules["reopen_within"])
            if line is not None:
                by_label[norm(line["label"])] = line
            if line is None and move == "open":
                n = max((s["n"] for s in lines), default=0) + 1
                line = {"id": f"sl:{match_id}:{n}", "matchId": match_id, "n": n, "label": item["label"].strip(),
                        "team": item["team"], "status": "active", "salience": 0.0, "openedAt": at,
                        "openedBy": analysis_id, "updatedAt": at, "resolvedAt": None, "outcome": None, "beats": [],
                        "keyEventIds": [], "quiet": 0, "linkedThrough": list(horizon), "lastAnalysisId": analysis_id,
                        "salienceHistory": []}
                lines.append(line)
                by_label[norm(line["label"])] = line
        if line is None or line["id"] in touched:
            continue
        touched.add(line["id"])
        line["beats"].append({"analysisId": analysis_id, "at": at, "headline": item["headline"],
                              "explanation": item.get("explanation"), "confidence": item["confidence"],
                              "evidence": item["facts"]})
        line.update(status="active", quiet=0, updatedAt=at, lastAnalysisId=analysis_id,
                    salience=round(item["confidence"] + rules["beat_weight"] * min(len(line["beats"]),
                                                                                  rules["beats_counted"]), 4))
    for item in resolves:
        _resolve(next(s for s in lines if s["id"] == item["storyline"]), item["outcome"], at, analysis_id)
    for line in lines:
        if line["status"] == "resolved" or line["id"] in touched:
            continue
        line.update(quiet=line["quiet"] + 1, salience=round(line["salience"] * rules["quiet_fade"], 4))
        if line["quiet"] >= rules["resolve_after"]:
            _resolve(line, FADED, at, analysis_id)
        elif line["quiet"] >= rules["dormant_after"]:
            line["status"] = "dormant"
    _link(lines, ledger, horizon, rules["key_event_boost"])
    active = sorted((s for s in lines if s["status"] == "active"), key=lambda s: (-s["salience"], s["n"]))
    for line in active[rules["max_active"]:]:
        line["status"] = "dormant"
    if final:
        for line in lines:
            if line["status"] != "resolved":
                _resolve(line, final_outcome, at, analysis_id)
    for line in lines:  # salience as of each analysis, so a reader bounded to a clock never sees a later value
        history = line.setdefault("salienceHistory", [])
        if not history or history[-1]["salience"] != line["salience"]:
            history.append({"at": at, "salience": line["salience"]})
    return lines


def _reopened(lines, label, clock, within):
    """The latest storyline with this label resolved within `within` match minutes, reopened (its earlier
    resolution kept in `resolutions`) instead of a second storyline of the same name; None if there is none."""
    line = max((s for s in lines if s["status"] == "resolved" and norm(s["label"]) == norm(label)
                and clock.timeMin - s["resolvedAt"]["timeMin"] <= within), key=lambda s: s["n"], default=None)
    if line is not None:
        line.setdefault("resolutions", []).append({"at": line["resolvedAt"], "outcome": line["outcome"]})
        line.update(resolvedAt=None, outcome=None)
    return line


def _resolve(line, outcome, at, analysis_id):
    line.update(status="resolved", outcome=outcome, resolvedAt=at, lastAnalysisId=analysis_id, updatedAt=at)


def _link(lines, ledger, horizon, boost):
    """Link the key events after each open storyline's last check, up to the horizon, that concern its
    team; each adds salience."""
    for line in lines:
        if line["status"] == "resolved":
            continue
        start = tuple(line["linkedThrough"])
        for row in sorted(ledger, key=lambda r: (r["periodId"], r["timeMin"], r["timeSec"], r["id"])):
            position = (row["periodId"], row["timeMin"], row["timeSec"])
            if start < position <= tuple(horizon) and row["keyType"] in boost and concerns(line, row) \
                    and row["id"] not in line["keyEventIds"]:
                line["keyEventIds"].append(row["id"])
                line["salience"] = round(line["salience"] + boost[row["keyType"]], 4)
        line["linkedThrough"] = list(horizon)


def choose_focus(lines, trigger_type, *, rules, key_row=None, turned=None, analysis_id=None, recent=()):
    """The one storyline a narrative step advances, shared by every bucket (None if there is none).
    A storyline turn focuses on that storyline; full time on those the final analysis resolved; a key
    event on the most salient storyline its team is part of; otherwise the most salient active (else
    dormant) storyline, with a penalty for each recent focus so the threads take turns."""
    if turned:
        return next((s for s in lines if s["id"] == turned), None)
    if trigger_type == "fullTime":
        pool = [s for s in lines if s["status"] == "resolved" and s["lastAnalysisId"] == analysis_id]
    else:
        pool = [s for s in lines if s["status"] == "active"] or [s for s in lines if s["status"] == "dormant"]
    if key_row is not None:
        pool = [s for s in pool if concerns(s, key_row)] or pool
    if not pool:
        return None
    recent = list(recent)[-rules["focus_recent_steps"]:] if rules["focus_recent_steps"] else []
    return max(pool, key=lambda s: (s["salience"] - rules["focus_repeat_penalty"] * recent.count(s["id"]), -s["n"]))
