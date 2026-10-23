"""Prompt templates per role, from the user backend's prompts API (the service) or the shipped files (tests and
devtools only). A template is used only if its placeholders equal the shipped file's; there is no fallback
(`PromptUnavailable`). Every prompt seen is kept by label, so a step pinned to one keeps it on retries."""
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from narrative_engine.transport.http_cache import CachedJson

PROMPTS = Path(__file__).parent / "prompts"
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
ROLES = ("minute-summary", "context-compression", "match-analyst", "narrative-author", "subscription-decision",
         "subscription-author")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Prompt:
    role: str
    label: str
    template: str


def placeholders(template):
    return set(PLACEHOLDER.findall(template))


def render_template(prompt, variables):
    """Fill `{name}` placeholders; JSON braces in the template are left alone."""
    missing = placeholders(prompt.template) - set(variables)
    if missing:
        raise KeyError(f"{prompt.label} needs {sorted(missing)}")
    return PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), prompt.template)


def shipped(role):
    """The highest-versioned prompts/{role}.vN.txt."""
    path = max(PROMPTS.glob(f"{role}.v*.txt"), key=lambda p: int(p.stem.rsplit(".v", 1)[1]))
    return Prompt(role, path.stem, path.read_text(encoding="utf-8"))


class ShippedPrompts:
    def __init__(self):
        self.seen = {}

    async def current(self, role):
        prompt = shipped(role)
        self.seen[prompt.label] = prompt
        return prompt

    async def pinned(self, role, label):
        return self.seen.get(label) or await self.current(role)


class PromptUnavailable(RuntimeError):
    pass


class HttpPromptSource:
    def __init__(self, base_url, client, max_age=5.0):
        self.document = CachedJson(client, f"{base_url.rstrip('/')}/narrative-prompts", max_age)
        self.seen, self.reported = {}, set()

    async def current(self, role):
        try:
            body = await self.document.get()
            item = next(p for p in body["prompts"] if p["role"] == role)
            prompt = Prompt(role, f"{role}@{int(item['version'])}", item["template"])
        except Exception as error:  # unreachable, malformed or missing role
            raise self._unavailable(f"prompt {role} unavailable from the user backend ({type(error).__name__})")
        if placeholders(prompt.template) != placeholders(shipped(role).template):
            raise self._unavailable(f"prompt {prompt.label} has the wrong placeholders")
        self.reported.clear()
        self.seen[prompt.label] = prompt
        return prompt

    async def pinned(self, role, label):
        return self.seen.get(label) or await self.current(role)

    async def problems(self):
        """Why the prompts cannot be used now (empty when healthy); refreshes at most every max_age."""
        try:
            for role in ROLES:
                await self.current(role)
        except PromptUnavailable as error:
            return [str(error)]
        return [] if self.document.ok else ["user backend unreachable (using its last answer)"]

    def _unavailable(self, problem):
        if problem not in self.reported:  # log each problem once, not on every retry
            self.reported.add(problem)
            log.warning(problem)
        return PromptUnavailable(problem)
