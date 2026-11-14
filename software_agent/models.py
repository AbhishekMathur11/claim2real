"""Data contracts for the software agent (search + validation of software requirements)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SearchTrace(BaseModel):  # same shape as the other agents' traces
    stage: str
    kind: Literal["search", "fetch", "tavily"]
    query_or_url: str
    provider: str
    status: str
    latency_ms: int | None
    results: int
    usage: dict | list | None = None


Kind = Literal["open-source", "commercial", "cloud service", "framework", "unknown"]


class SoftwareCandidate(BaseModel):
    requirement: str
    name: str
    provider: str            # organisation / maintainer
    url: str
    domain: str
    kind: Kind = "unknown"
    reason: str
    found_by_provider: str
    found_by_query: str


class SoftwareSource(BaseModel):
    url: str
    domain: str
    title: str = ""
    engine: str = ""


class SoftwareAssessment(BaseModel):
    candidate: SoftwareCandidate
    decision: Literal["keep", "eliminate"]
    reason: str
    validation: Literal["validated", "partially validated", "unvalidated"]
    license: str = "unknown"
    cost_model: str = "unknown"          # free / open-source | paid license | subscription | unknown
    maintenance: str = "unknown"         # active | maintained | stale | unknown
    maturity: str = "unknown"            # production | research | experimental | unknown
    integration: str = ""                # e.g. "ROS 2 package available"
    fit: Literal["good", "partial", "poor", "unknown"] = "unknown"
    rank: int = 0
    sources: list[SoftwareSource] = []
