"""LLM client seam: mock for tests, HTTP clients for live (key-gated).

The agents depend on this Protocol, never on a vendor SDK, so tests are fully
offline-deterministic and the live path stays a thin, auditable HTTP call.
Two interchangeable live backends — Anthropic (ANTHROPIC_API_KEY) and OpenAI
(OPENAI_API_KEY) — because the agent contracts are vendor-agnostic; use
``default_client()`` to pick whichever key is configured. NOTE: consumer chat
subscriptions (ChatGPT Pro / Claude Pro) do NOT grant API access; both
backends need a pay-as-you-go API key. Without any key, complete() raises and
the caller treats the agent layer as absent (shadow artifacts simply don't
get produced — never a trading halt).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"


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


class OpenAIHTTPClient:
    """Minimal OpenAI chat-completions client (no SDK). Key-gated.

    Works with any OpenAI API key (pay-as-you-go platform account). A ChatGPT
    Pro/Plus subscription is NOT an API key — the API is billed separately.
    """

    def __init__(self, model_id: str = DEFAULT_OPENAI_MODEL, timeout: float = 60.0) -> None:
        self.model_id = model_id
        self.timeout = timeout

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set - agent layer is inert without it")
        body = json.dumps(
            {
                "model": self.model_id,
                "max_completion_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode()
        req = urllib.request.Request(
            OPENAI_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        return parse_openai_payload(payload)


def parse_openai_payload(payload: dict) -> str:
    """Pure parser for a chat-completions response (unit-testable)."""

    choices = payload.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return str(message.get("content") or "")


def default_client() -> LLMClient | None:
    """Pick a live client from whichever API key is configured, else None."""

    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicHTTPClient()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIHTTPClient()
    return None
