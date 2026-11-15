"""Secrets and defaults. Never print keys."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
load_dotenv(HERE / ".env")
load_dotenv(REPO / "requirements_agent" / ".env")
load_dotenv(REPO / ".env")  # one repo-root .env serves every agent

TAVILY_KEY_RE = re.compile(r"tvly-[A-Za-z0-9_-]+")
ANTHROPIC_KEY_RE = re.compile(r"sk-ant-(?:api|oat|usr)[A-Za-z0-9_-]+")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")


def _yaml_blob(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def tavily_key() -> str:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if key:
        return key
    blob = _yaml_blob(HERE / "api.yaml")
    try:
        data = yaml.safe_load(blob) or {}
    except yaml.YAMLError:
        data = {}
    if isinstance(data, dict):
        tavily = data.get("tavily")
        if isinstance(tavily, str) and tavily.strip():
            return tavily.strip()
        if isinstance(tavily, dict):
            return str(tavily.get("api_key") or tavily.get("key") or "").strip()
    match = TAVILY_KEY_RE.search(blob)
    if match:
        return match.group(0)
    cfg = Path.home() / ".tavily" / "config.json"
    if cfg.exists():
        try:
            stored = json.loads(cfg.read_text())
            return str(stored.get("api_key") or stored.get("token") or "").strip()
        except json.JSONDecodeError:
            return ""
    raise SystemExit("Set TAVILY_API_KEY or put a tavily key in api.yaml")


def anthropic_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    for path in (HERE / "api.yaml", REPO / "requirements_agent" / "api.yaml"):
        blob = _yaml_blob(path)
        match = ANTHROPIC_KEY_RE.search(blob)
        if match:
            return match.group(0)
    raise SystemExit("Set ANTHROPIC_API_KEY for email drafts")
