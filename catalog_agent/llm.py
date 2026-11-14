"""JSON-only LLM calls via OpenRouter (OpenAI-compatible), validated by Pydantic, with one retry."""
from __future__ import annotations

import json
import re
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

import config

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL)
    return _client


def _extract_json(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        return fence.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    return text[start:] if start > 0 else text


_AFFORD_RE = re.compile(r"can only afford (\d+)")


def _create(messages: list[dict], max_tokens: int):
    """Chat completion; on OpenRouter 402 'can only afford N', retry once with fewer tokens."""
    kwargs = dict(model=config.LLM_MODEL, messages=messages, response_format={"type": "json_object"})
    try:
        return _get_client().chat.completions.create(max_tokens=max_tokens, **kwargs)
    except Exception as e:  # noqa: BLE001
        m = _AFFORD_RE.search(str(e))
        if not m or int(m.group(1)) < 300:
            raise
        return _get_client().chat.completions.create(max_tokens=int(m.group(1)) - 50, **kwargs)


def call_json(system: str, user: str, schema: type[T], max_tokens: int = 4096) -> T:
    """Ask the model for JSON matching `schema`. Retries once, feeding back the error."""
    schema_hint = json.dumps(schema.model_json_schema())
    sys_prompt = (
        f"{system}\n\nRespond with ONLY a JSON object matching this JSON schema, no prose:\n{schema_hint}"
    )
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    last_err: Exception | None = None
    for _ in range(2):
        resp = _create(messages, max_tokens)
        text = resp.choices[0].message.content or ""
        try:
            return schema.model_validate_json(_extract_json(text))
        except (ValidationError, ValueError) as e:
            last_err = e
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That was not valid. Error: {e}. Return only corrected JSON."},
            ]
    raise ValueError(f"LLM JSON validation failed twice: {last_err}")
