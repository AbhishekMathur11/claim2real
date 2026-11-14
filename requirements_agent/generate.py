#!/usr/bin/env python3
"""Fill a RequirementsChecklist JSON from a problem statement via OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from config import CANONICAL_FIELDS
from models import parse_bundle

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")
KEY_RE = re.compile(r"sk-or-v1-[A-Za-z0-9]+")


def api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    blob = (ROOT / "api.yaml").read_text() if (ROOT / "api.yaml").exists() else ""
    match = KEY_RE.search(blob)
    if match:
        return match.group(0)
    sys.exit("Set OPENROUTER_API_KEY in .env or put an OpenRouter key in api.yaml")


def client() -> OpenAI:
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key())


def _prompt_text(name: str) -> str:
    return (ROOT / "prompts" / name).read_text()


def _fields_block() -> str:
    lines = []
    for name, unit in CANONICAL_FIELDS.items():
        if unit is None:
            lines.append(f"- {name}: categorical, operator has, unit null")
        else:
            lines.append(f"- {name}: numeric, unit {unit}, value is a number")
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_spec(
    problem: str,
    *,
    spec: str | None = None,
    refine: str | None = None,
    model: str = DEFAULT_MODEL,
) -> str:
    problem = problem.strip()
    schema = _prompt_text("spec_template.md")
    fields = _fields_block()
    if spec and refine:
        user = (
            f"Canonical fields:\n{fields}\n\n"
            f"Schema example:\n{schema}\n\n"
            f"Original problem:\n{problem}\n\n"
            f"Current checklist:\n{spec.strip()}\n\n"
            f"Revision notes:\n{refine.strip()}\n\n"
            "Return {\"checklists\":[...]} with updated RequirementsChecklist objects."
        )
    else:
        user = (
            f"Canonical fields:\n{fields}\n\n"
            f"Schema example:\n{schema}\n\n"
            f"Problem statement:\n{problem}\n\n"
            "Return {\"checklists\":[...]} — one RequirementsChecklist per sourceable component."
        )

    max_tokens = 2500
    try:
        response = client().chat.completions.create(
            model=model,
            temperature=0.1,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _prompt_text("system.md")},
                {"role": "user", "content": user},
            ],
        )
    except Exception as exc:
        afford = re.search(r"can only afford (\d+)", str(exc))
        if not afford or int(afford.group(1)) < 400:
            raise
        response = client().chat.completions.create(
            model=model,
            temperature=0.1,
            max_tokens=int(afford.group(1)) - 50,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _prompt_text("system.md")},
                {"role": "user", "content": user},
            ],
        )

    raw = _strip_fence(response.choices[0].message.content or "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"RequirementsChecklist invalid JSON:\n{exc}\n{raw}") from exc
    if not isinstance(data, dict):
        raise SystemExit("RequirementsChecklist invalid: expected a JSON object")
    bundle = parse_bundle(data, problem)
    return bundle.model_dump_json(indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", default="")
    parser.add_argument("--problem-file", type=Path)
    parser.add_argument("--spec", type=Path, help="Existing checklist JSON to revise")
    parser.add_argument("--refine", default="", help="Revision notes")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    problem = args.problem
    if args.problem_file:
        problem = args.problem_file.read_text()
    if not problem.strip():
        sys.exit("Pass --problem or --problem-file")

    spec_text = args.spec.read_text() if args.spec else None
    if args.refine and not spec_text:
        sys.exit("--refine needs --spec")

    filled = generate_spec(
        problem, spec=spec_text, refine=args.refine or None, model=args.model
    )
    if args.out:
        args.out.write_text(filled + "\n")
    print(filled)


if __name__ == "__main__":
    main()
