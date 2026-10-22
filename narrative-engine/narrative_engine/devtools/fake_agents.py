"""Deterministic stand-in agents for tests and offline runs. No model calls."""
import asyncio
import json
import re

from narrative_engine.core.models import AgentResult


class FakeAgents:
    def __init__(self, author_delay=0.0, delay=0.0):
        self.calls = []  # (agent, variables) in call order
        self.author_delay, self.delay = author_delay, delay
        self.running = self.max_running = 0  # author calls in flight
        self.in_flight = self.max_in_flight = 0  # any calls in flight

    async def _busy(self, seconds, author=False):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        if author:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(seconds)
        finally:
            self.in_flight -= 1
            if author:
                self.running -= 1

    async def summarise(self, variables, prompt=None):
        self.calls.append(("summarise", variables))
        await self._busy(self.delay)
        first = variables["match_events"].splitlines()[0]
        return AgentResult(f"Summary of {first}", "fake", version(prompt))

    async def compress(self, variables, prompt=None):
        self.calls.append(("compress", variables))
        await self._busy(self.delay)
        count = variables["summaries"].count("\n[") + 1
        return AgentResult(f"Compression of {count} summaries", "fake", version(prompt))

    async def analyse(self, variables, prompt=None, feedback=None):
        """One observation per team from the longest trend window shown: its first flagged number (else its
        first), developing that storyline when it is open, else opening it. At full time resolves the rest."""
        self.calls.append(("analyse", variables))
        await self._busy(self.delay)
        table = variables["match_trends"]
        names = dict(TEAMS.findall(table))  # code -> name
        cells = {}  # window -> code -> [(indicator, value, note)]
        for window, body in WINDOW.findall(table):
            for indicator, row in INDICATOR.findall(body):
                for code, value, note in CELL.findall(row):
                    cells.setdefault(window, {}).setdefault(code, []).append((indicator, value, note))
        observations = []
        for window in ("match", "half", "last15", "last5"):
            for code, values in cells.get(window, {}).items():
                indicator, value, note = next((v for v in values if v[2]), values[0])
                label = f"{code} {indicator}"
                found = re.search(rf"^- (\S+) \[{re.escape(label)}\] \((active|dormant)", variables["storylines"], re.M)
                observations.append({"label": label, "team": code, "headline": f"{names[code]} {indicator} {value}",
                                     "confidence": "medium" if window == "last5" else "high",
                                     "evidence": [{"indicator": indicator, "team": code, "window": window,
                                                   "value": float(value)}],
                                     "storyline": found.group(1) if found else "open"})
            if observations:
                break
        resolve = []
        if variables["analysis_reason"].startswith("Full time"):
            resolve = [{"storyline": i, "outcome": "Full time."}
                       for i in re.findall(r"^- (\S+) \[.*\] \((?:active|dormant)", variables["storylines"], re.M)]
        return AgentResult(json.dumps({"observations": observations, "resolve": resolve}), "fake", version(prompt))

    async def author(self, variables, prompt=None, feedback=None):
        self.calls.append(("author", variables))
        await self._busy(self.author_delay, author=True)
        reason = variables["trigger_reason"].splitlines()[0]
        return AgentResult(f"[{variables['bucket_id']}] {reason}", "fake", version(prompt))


# context.render.render_trend_table
TEAMS = re.compile(r"(\w+) = ([^,(]+?) \((?:home|away)\)")
WINDOW = re.compile(r'^window "(\w+)" \([^)]*\):\n((?:  .+\n?)+)', re.M)
INDICATOR = re.compile(r"^  ([^:\n]+): (.+)$", re.M)
CELL = re.compile(r"(\w+) (-?[\d.]+)(?:m|/5min)?( \([^)]*\))?(?: \||$)")


def version(prompt):
    return f"fake:{prompt.label}" if prompt else "fake-v1"
