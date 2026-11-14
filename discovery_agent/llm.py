"""JSON-only Claude calls via the Anthropic SDK, validated by Pydantic structured outputs.

`call_json(system, user, Schema)` returns a validated `Schema` instance. Structured outputs
(`messages.parse(output_format=Schema)`) constrain the reply to the schema, so there is no
free-text JSON scraping. One retry on a truncated or unparseable reply.

Defaults (config.py / .env): model claude-haiku-5-5 (cheapest current Claude), effort "low",
thinking off - these are short extraction / classification calls, so extra reasoning only adds
cost and latency.
"""
from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

import config

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None
# Running totals for this process (for cost reporting).
USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # api_key=None lets the SDK fall back to ANTHROPIC_API_KEY / an `ant auth login` profile.
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)
    return _client


def call_json(system: str, user: str, schema: type[T], max_tokens: int = 4096) -> T:
    """Ask Claude for output matching `schema`. Raises on refusal or after two failed attempts."""
    params: dict = dict(
        model=config.LLM_MODEL,
        max_tokens=max(max_tokens, config.LLM_MIN_MAX_TOKENS),  # only generated tokens are billed
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": config.LLM_EFFORT},
    )
    if config.LLM_THINKING == "off":
        params["thinking"] = {"type": "disabled"}

    last_err = "no response"
    for _ in range(2):
        resp = _get_client().messages.parse(**params)
        USAGE["calls"] += 1
        USAGE["input_tokens"] += resp.usage.input_tokens
        USAGE["output_tokens"] += resp.usage.output_tokens
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined the request: {resp.stop_details}")
        if resp.stop_reason == "max_tokens":
            last_err = f"reply truncated at max_tokens={params['max_tokens']}"
            params["max_tokens"] *= 2
            continue
        if resp.parsed_output is not None:
            return resp.parsed_output
        last_err = f"no parsed output (stop_reason={resp.stop_reason})"
    raise ValueError(f"LLM JSON call failed twice: {last_err}")
