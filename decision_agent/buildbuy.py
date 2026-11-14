"""Build vs Buy agent: one recommendation per hardware and software requirement.

Input is the final shortlist (per requirement: what survived verification and what was eliminated,
with prices, scores, vendor risk, licenses, maintenance). Claude recommends buy / build / hybrid using
ONLY that data plus clearly-labelled engineering estimates. Without the LLM, a rule-based decision is
made from the shortlist (verified option within budget -> buy; none -> build or hybrid).

CLI (from decision_agent/):  python buildbuy.py shortlist.json --out cache/buildbuy.json
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

import llm

WORKERS = 6


class Decision(BaseModel):
    decision: Literal["buy", "build", "hybrid"]
    confidence: Literal["high", "medium", "low"]
    headline: str
    reasons: list[str]
    risks: list[str]
    next_step: str


class Recommendation(Decision):
    requirement: str
    kind: Literal["hardware", "software"]
    source: Literal["llm", "rules"] = "llm"


SYSTEM = """You advise a robotics team whether to BUY, BUILD or go HYBRID for one requirement.
- buy: adopt an existing product (hardware purchase, commercial software, or an open-source package used as-is)
- build: design it in-house
- hybrid: adopt an existing base and customise / integrate significantly
Use ONLY the shortlist data given: surviving options (verified claims, price vs budget, vendor risk,
license, maintenance, maturity) and the eliminated options with reasons. You may add engineering
judgement about build effort, but label it as an estimate. Never invent products, prices or facts.
Prefer buy when a verified, low/medium-risk option meets the requirement within budget. Prefer build or
hybrid when nothing survived, options are over budget, or the requirement is core differentiating IP.
Return: decision, confidence, headline (one sentence), reasons (2-4 short bullets citing the data),
risks (1-3 bullets), next_step (one concrete action)."""


def _prompt(problem: str, r: dict) -> str:
    return json.dumps({"problem": problem, "requirement": r}, indent=1, default=str)[:14000]


def rules(r: dict) -> Decision:
    kept = r.get("kept") or []
    if r["kind"] == "hardware":
        if kept:
            top = kept[0]
            return Decision(decision="buy", confidence="medium",
                            headline=f"Buy: {top.get('name')} passed verification for this requirement.",
                            reasons=[f"{len(kept)} option(s) passed elimination", f"Top score {top.get('score')}"],
                            risks=["Rule-based recommendation (LLM unavailable)"], next_step="Request a quote and datasheet.")
        return Decision(decision="build" if not r.get("eliminated") else "hybrid", confidence="low",
                        headline="No off-the-shelf option passed verification.",
                        reasons=[f"{len(r.get('eliminated') or [])} option(s) eliminated"],
                        risks=["Rule-based recommendation (LLM unavailable)"],
                        next_step="Widen the search or relax a must-have, then re-run.")
    if kept:
        return Decision(decision="buy", confidence="medium", headline=f"Adopt {kept[0].get('name')}.",
                        reasons=[f"{len(kept)} validated option(s)"], risks=["Rule-based recommendation (LLM unavailable)"],
                        next_step="Prototype the top option in the robot stack.")
    return Decision(decision="build", confidence="low", headline="No validated existing software found.",
                    reasons=["All candidates eliminated"], risks=["Rule-based recommendation (LLM unavailable)"],
                    next_step="Scope an in-house implementation.")


def decide(problem: str, r: dict) -> Recommendation:
    try:
        d = llm.call_json(SYSTEM, _prompt(problem, r), Decision, 1200)
        src = "llm"
    except Exception as e:  # noqa: BLE001
        print(f"[buildbuy] LLM failed for {r['name']!r}: {str(e)[:150]}", file=sys.stderr)
        d, src = rules(r), "rules"
    return Recommendation(requirement=r["name"], kind=r["kind"], source=src, **d.model_dump())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("shortlist", type=Path, help="final per-requirement shortlist JSON (written by the UI workflow)")
    ap.add_argument("--out", type=Path, default=Path("cache/buildbuy.json"))
    args = ap.parse_args()
    data = json.loads(args.shortlist.read_text())
    reqs = data.get("requirements", [])
    with ThreadPoolExecutor(WORKERS) as ex:
        recs = list(ex.map(lambda r: decide(data.get("problem", ""), r), reqs))
    for rec in recs:
        print(f"[{rec.kind:<8}] {rec.requirement}: {rec.decision.upper()} ({rec.confidence}) — {rec.headline}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"recommendations": [r.model_dump() for r in recs]}, indent=2))
    print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    main()
