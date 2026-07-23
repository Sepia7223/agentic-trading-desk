"""LLM client seam: mock for tests, HTTP client for live (key-gated).

The agents depend on this Protocol, never on a vendor SDK, so tests are fully
offline-deterministic and the live path stays a thin, auditable HTTP call.
Live calls require ANTHROPIC_API_KEY; without it, complete() raises and the
caller treats the agent layer as absent (shadow artifacts simply don't get
produced — never a trading halt).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-4-5"


class LLMClient(Protocol):
    model_id: str

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """Return the model's text response for one prompt."""
        ...


class MockLLMClient:
    """Deterministic canned-response client for tests and dry runs."""

    def __init__(self, responses: list[str], model_id: str = "mock") -> None:
        self._responses = list(responses)
        self.model_id = model_id
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise RuntimeError("mock exhausted")
        return self._responses.pop(0)


class AnthropicHTTPClient:
    """Minimal live client (no SDK dependency). Key-gated; fails loudly."""

    def __init__(self, model_id: str = DEFAULT_MODEL, timeout: float = 60.0) -> None:
        self.model_id = model_id
        self.timeout = timeout

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set - agent layer is inert without it")
        body = json.dumps(
            {
                "model": self.model_id,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        ).encode()
        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        parts = payload.get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text")
