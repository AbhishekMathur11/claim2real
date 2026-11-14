"""Shared data contracts (spec section 6), aligned with requirements_agent/models.py.

The Requirements agent validates strictly (canonical fields, units) and emits
{"checklists": [...]}: one checklist per sourceable component. Downstream we accept
that output as-is; see `load_checklists`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Requirement(BaseModel):  # == requirements_agent Constraint
    field: str
    operator: Literal[">=", "<=", "==", "has"]
    value: float | int | str
    unit: str | None = None


class RequirementsChecklist(BaseModel):
    component_type: str
    must_have: list[Requirement]
    nice_to_have: list[Requirement] = []
    budget_usd: float | None = None
    max_lead_time_days: int | None = None
    ship_to: str | None = None
    quantity: int = 1
    assumptions: list[str] = []
    problem_statement: str | None = None
    search_terms: list[str] = []


class RequirementsBundle(BaseModel):
    checklists: list[RequirementsChecklist] = Field(min_length=1)


def load_checklists(path: str | Path) -> list[RequirementsChecklist]:
    """Read Requirements-agent output: a {"checklists": [...]} bundle or a single checklist."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and "checklists" in data:
        return RequirementsBundle.model_validate(data).checklists
    return [RequirementsChecklist.model_validate(data)]


class Candidate(BaseModel):
    name: str
    vendor: str
    url: str
    vendor_domain: str
    found_by_provider: str
    found_by_query: str
    reason: str
    component_type: str | None = None  # which checklist this candidate answers


class Claim(BaseModel):
    field: str
    value: float | str
    unit: str | None
    quote: str
    source_url: str
    fit: Literal["meets", "fails", "unknown"] = "unknown"


class CandidateProfile(BaseModel):
    candidate: Candidate
    claims: list[Claim]
    price_usd: float | None = None
    availability: str | None = None
    contact: str | None = None
    extraction_engine: Literal["telem", "tavily"] = "telem"
    # Additions (optional): per-requirement fit and page diagnostics for the UI/scoring.
    product_name: str | None = None
    requirement_fit: dict[str, Literal["meets", "fails", "unknown"]] = {}  # field -> fit ("budget" too)
    price_quote: str | None = None
    datasheet_urls: list[str] = []
    page_status: str = "ok"  # "ok" | "unreadable" | "extraction_failed"
    dropped_claims: int = 0  # LLM claims discarded because their quote was not on the page


class Evidence(BaseModel):
    url: str
    domain: str
    note: str
    engine: str  # "telem:<provider>" | "tavily"


class ClaimVerdict(BaseModel):
    claim: Claim
    verdict: Literal["verified", "contradicted", "unverified"]
    evidence: list[Evidence]


class VerifiedCandidate(BaseModel):
    profile: CandidateProfile
    verdicts: list[ClaimVerdict]
    vendor_risk: Literal["low", "medium", "high"]
    vendor_risk_reason: str
    score: float
    meets_requirements: bool


class SearchTrace(BaseModel):
    stage: str
    kind: Literal["search", "fetch", "tavily"]
    query_or_url: str
    provider: str
    status: str
    latency_ms: int | None
    results: int
    usage: dict | list | None = None


class SourcingReport(BaseModel):
    checklist: RequirementsChecklist
    ranked: list[VerifiedCandidate]
    emails: dict[str, str]
    telem_session_id: str
    traces: list[SearchTrace]
