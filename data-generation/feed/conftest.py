"""The feed's tests need its own requirements (feed/requirements-test.txt); the rest of
data-generation runs with pytest alone, so skip collecting them when those are missing."""
import importlib.util

collect_ignore_glob = [] if all(importlib.util.find_spec(m) for m in ("fastapi", "httpx")) else ["tests/*"]
