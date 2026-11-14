#!/usr/bin/env python3
"""Local UI for the requirements agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

AGENT = Path(__file__).resolve().parents[1] / "requirements_agent"
sys.path.insert(0, str(AGENT))

from generate import generate_spec  # noqa: E402
from models import parse_bundle  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SPEC_PATH = DATA / "current.json"
STATIC = ROOT / "static"

app = FastAPI(title="claim2real requirements")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class GenerateBody(BaseModel):
    problem: str


def _problem_from(bundle: dict) -> str:
    items = bundle.get("checklists") or []
    if items and isinstance(items[0], dict):
        return str(items[0].get("problem_statement") or "")
    return ""


def _save(bundle: dict) -> dict:
    DATA.mkdir(exist_ok=True)
    SPEC_PATH.write_text(json.dumps(bundle, indent=2) + "\n")
    return bundle


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/spec")
def get_spec() -> dict:
    if not SPEC_PATH.exists():
        return {"hardware": [], "software": [], "checklists": []}
    return json.loads(SPEC_PATH.read_text())


@app.post("/api/generate")
def generate(body: GenerateBody) -> dict:
    problem = body.problem.strip()
    if not problem:
        raise HTTPException(400, "Problem statement is empty")
    try:
        bundle = json.loads(generate_spec(problem))
    except SystemExit as exc:
        detail = str(exc)
        if "invalid JSON" in detail:
            detail = "Model output was truncated. Retry the same task."
        raise HTTPException(400, detail[:400]) from exc
    except Exception as exc:
        raise HTTPException(502, f"Generation failed: {exc}") from exc
    return _save(bundle)


@app.post("/api/spec")
def update_spec(body: dict) -> dict:
    problem = _problem_from(body)
    if not problem:
        raise HTTPException(400, "checklists[0].problem_statement is required")
    try:
        bundle = parse_bundle(body, problem)
    except (SystemExit, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return _save(json.loads(bundle.model_dump_json()))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
