"""Anthropic JSON helper for people extraction and email drafts."""

from __future__ import annotations

import re

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

import config

_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        secret = config.anthropic_key()
        if secret.startswith("sk-ant-oat"):
            _client = Anthropic(auth_token=secret, timeout=90.0)
        else:
            _client = Anthropic(api_key=secret, timeout=90.0)
    return _client


def _strip(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return text


def _complete(system: str, user: str, max_tokens: int) -> str:
    kwargs = dict(
        model=config.MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low"},
    )
    try:
        response = client().messages.create(**kwargs)
    except Exception:
        kwargs.pop("output_config", None)
        response = client().messages.create(**kwargs)
    return "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", "") == "text"
    )


def call_text(system: str, user: str, max_tokens: int = 8192) -> str:
    text = _complete(system, user, max_tokens).strip()
    if not text:
        raise SystemExit("Model returned an empty report.")
    return text


def call_json(system: str, user: str, schema: type[BaseModel], max_tokens: int = 4096) -> BaseModel:
    raw = _complete(system, user, max_tokens)
    try:
        return schema.model_validate_json(_strip(raw))
    except (ValidationError, ValueError) as exc:
        raise SystemExit(f"Outreach JSON invalid:\n{exc}\n{raw[:800]}") from exc
