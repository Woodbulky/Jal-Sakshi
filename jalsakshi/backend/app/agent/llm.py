"""Swappable LLM adapter — for wording, never for decisions.

What the model is allowed to do here is narrate: turn a decision that has
already been made deterministically into a sentence a field actor or a
committee member can read. What it is not allowed to do is choose the fault,
the crew, the priority, the SLA, or whether an incident may close. Those come
from `signatures.py`, `policy.py` and `verification.py`, and they are the same
with the model switched off.

That boundary is why the stub is a first-class implementation rather than a
degraded mode: with `LLM_PROVIDER=none` the system loses phrasing and keeps
every guarantee. The demo runs either way.

Groq, OpenAI and any other OpenAI-wire-compatible provider go through
`OpenAICompatibleReasoner` on a base URL. Anthropic and Google would each need
their own subclass; the seam is `Reasoner`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

#: Kept short and rule-shaped: the model is being asked to write, not to think
#: about what should happen.
SYSTEM_PROMPT = """You write field messages for JAL-SAKSHI, a rural water
operations system in India.

You are given a decision that has already been made by deterministic
engineering logic. Your only job is to express it clearly.

Rules:
- Never contradict, re-rank or second-guess the decision you are given.
- Never invent a cause, a number, a household count or a deadline.
- Write for a field worker with a phone, not for an engineer.
- Two or three short sentences. No preamble, no markdown, no emoji.
- If the diagnosis is UNKNOWN, say plainly that the cause is not yet known and
  that an inspection is needed."""


class Reasoner(Protocol):
    """The seam. Everything downstream depends on this, not on a provider."""

    @property
    def name(self) -> str: ...

    async def narrate(self, context: dict[str, Any]) -> str:
        """One or two sentences describing a decision already made."""
        ...


class StubReasoner:
    """Deterministic phrasing. The default, and what the tests run against.

    Not a placeholder: it produces the same operationally correct message every
    time, which is exactly what you want in a system where the sentence is
    read by someone deciding whether to get on a motorcycle at night.
    """

    @property
    def name(self) -> str:
        return "stub"

    async def narrate(self, context: dict[str, Any]) -> str:
        fault = str(context.get("fault_type", "UNKNOWN")).replace("_", " ").lower()
        asset = context.get("asset_code") or "an asset"
        households = context.get("households_affected") or 0
        action = context.get("action_summary") or "Inspect and report."
        sla = context.get("sla_hours")

        if context.get("sensor_health_blocked"):
            return (
                f"Instrument problem on {asset}: the network is supplying "
                f"normally but the sensor cannot be believed. {action}"
            )
        if str(context.get("fault_type")) == "UNKNOWN":
            return (
                f"Unexplained readings around {asset}. The cause is not yet "
                f"known, so no repair has been assumed. {action}"
            )

        lead = f"Suspected {fault} at {asset}."
        if households:
            lead += f" About {households} households are affected."
        if sla:
            lead += f" Restore within {sla:.0f} hours."
        return f"{lead} {action}"


class OpenAICompatibleReasoner:
    """Groq, OpenAI, or anything else speaking the same wire format.

    Any failure — timeout, rate limit, malformed response — falls back to the
    stub. An operations system does not stop dispatching crews because a
    inference endpoint is having a bad afternoon.
    """

    def __init__(self, settings: Settings, *, fallback: Reasoner | None = None) -> None:
        self._settings = settings
        self._fallback = fallback or StubReasoner()
        self._base_url = settings.resolved_llm_base_url

    @property
    def name(self) -> str:
        return f"{self._settings.llm_provider}:{self._settings.llm_model}"

    async def narrate(self, context: dict[str, Any]) -> str:
        payload = {
            "model": self._settings.llm_model,
            "temperature": self._settings.llm_temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context, default=str)},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.llm_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
                )
                response.raise_for_status()
                body = response.json()
            text = body["choices"][0]["message"]["content"].strip()
        except Exception as error:  # noqa: BLE001 -- any failure degrades, none propagates
            logger.warning("llm narration failed (%s); using stub", error)
            return await self._fallback.narrate(context)

        if not text:
            return await self._fallback.narrate(context)
        return text


def build_reasoner(settings: Settings) -> Reasoner:
    """Pick an implementation from configuration. Unconfigured -> stub."""
    if not settings.llm_configured:
        return StubReasoner()
    if settings.llm_provider in ("groq", "openai") or settings.llm_base_url:
        return OpenAICompatibleReasoner(settings)
    logger.warning(
        "LLM_PROVIDER=%s has no adapter yet; using the deterministic stub",
        settings.llm_provider,
    )
    return StubReasoner()


__all__ = [
    "SYSTEM_PROMPT",
    "OpenAICompatibleReasoner",
    "Reasoner",
    "StubReasoner",
    "build_reasoner",
]
