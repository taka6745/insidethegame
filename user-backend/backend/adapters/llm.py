"""Environment-configured OpenAI-compatible development model; no provider coupling."""
import json
import os
import logging
from typing import Protocol

import httpx


class ModelError(RuntimeError):
    def __init__(self, message: str, *, reason="model_error", retryable=True):
        super().__init__(message)
        self.reason, self.retryable = reason, retryable


class JsonModel(Protocol):
    async def complete(self, system: str, payload: dict) -> dict: ...


class LocalJsonModel:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 120,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_env(cls):
        url, model = os.getenv("LOCAL_LLM_BASE_URL"), os.getenv("LOCAL_LLM_MODEL")
        if not url or not model:
            raise ModelError("Configure LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL for local model mode")
        return cls(url, model, os.getenv("LOCAL_LLM_API_KEY", ""),
                   float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "120")))

    async def complete(self, system: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(self.base_url + "/chat/completions", headers=headers, json={
                    "model": self.model, "stream": False, "temperature": 0,
                    "max_tokens": 3000,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": json.dumps(payload)}],
                })
                response.raise_for_status()
                choice = response.json()["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ModelError("Local model output was truncated", reason="truncated_output")
                content = choice["message"]["content"]
                if not isinstance(content, str) or len(content) > 30000:
                    raise ValueError("Invalid response content")
                # Accept a single fenced JSON object, never execute model output.
                content = content.strip()
                if content.startswith("```json\n") and content.endswith("```"):
                    content = content[8:-3].strip()
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError("Expected a JSON object")
                return result
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logging.getLogger(__name__).warning("Local model HTTP failure: status=%s", status)
            raise ModelError("Local model request failed", reason=f"http_{status}",
                             retryable=status in {408, 429} or status >= 500) from None
        except httpx.HTTPError:
            logging.getLogger(__name__).warning("Local model transport failure")
            raise ModelError("Local model request failed", reason="transport_error") from None
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            # Do not expose request URLs, tokens, provider bodies or model output to viewers/logs.
            logging.getLogger(__name__).warning("Local model returned an invalid JSON object")
            raise ModelError("Local model request failed or returned invalid JSON", reason="invalid_json") from None
