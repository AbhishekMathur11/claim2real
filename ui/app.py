#!/usr/bin/env python3
"""Local UI: requirements agent + sourcing pipeline (Discovery -> Catalog -> Verifier)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

AGENT = Path(__file__).resolve().parents[1] / "requirements_agent"
sys.path.insert(0, str(AGENT))
# One repo-root .env serves every agent (requirements_agent also reads its own .env if present).
load_dotenv(AGENT.parent / ".env")

import workflow  # noqa: E402  (ui/workflow.py; runs the other agents as subprocesses)

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


class RunBody(BaseModel):
    limit: int | None = None       # hardware candidates per requirement (default: discovery config)


class Sender(BaseModel):
    name: str = ""
    company: str = ""


@app.post("/api/run")
def start_run(body: RunBody) -> dict:
    """Start search on the SAVED spec: hardware discovery per requirement + software discovery."""
    if not SPEC_PATH.exists():
        raise HTTPException(400, "Generate and save the requirements first")
    spec = json.loads(SPEC_PATH.read_text())
    if not spec.get("checklists") and not spec.get("software"):
        raise HTTPException(400, "The spec has no hardware or software requirements")
    return workflow.start(spec, body.limit).status()


@app.post("/api/run/{run_id}/verify")
def verify_run(run_id: str, body: Sender) -> dict:
    """Start verification (+ build vs buy + final agent) for a finished search."""
    run = workflow.RUNS_BY_ID.get(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run")
    try:
        run.start_verify({"name": body.name.strip(), "company": body.company.strip()})
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return run.status()


@app.get("/api/run/latest")
def latest_run() -> dict:
    run = workflow.latest()
    if run is None:
        raise HTTPException(404, "No run yet")
    return run.status()


@app.get("/api/run/{run_id}")
def run_status(run_id: str) -> dict:
    run = workflow.RUNS_BY_ID.get(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run")
    return run.status()


@app.get("/api/run/{run_id}/download/{name}")
def run_file(run_id: str, name: str) -> FileResponse:
    """Download a run artifact: hw<i>_report.md, final/report.md, final/outreach.md, shortlist.json ..."""
    run = workflow.RUNS_BY_ID.get(run_id)
    allowed = {"shortlist.json", "buildbuy.json", "final_input.md", "report.md", "outreach.md", "outreach.json"}
    if run is None or not (name in allowed or (name.startswith("hw") and name.endswith("_report.md"))):
        raise HTTPException(404, "Unknown file")
    path = run.dir / ("final/" + name if name in {"report.md", "outreach.md", "outreach.json"} else name)
    if not path.exists():
        raise HTTPException(404, "Not generated yet")
    return FileResponse(path, filename=f"{run.id}-{name.replace('/', '_')}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
