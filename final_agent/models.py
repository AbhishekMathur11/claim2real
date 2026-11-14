"""Outreach pack: companies in, people + draft emails out."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Sender(BaseModel):
    name: str
    company: str
    context: str = ""


class Candidate(BaseModel):
    rank: str | int | None = None
    product: str = ""
    company: str = ""  # manufacturer
    seller: str = ""
    seller_url: str = ""
    score: float | None = None
    risk: str = ""
    meets_reqs: bool | None = None
    verified_contradicted: str = ""
    verdicts: str = ""
    recommendation: str = ""
    sellers: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value):
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace("–", "-").split("-")[0].strip()
        try:
            return float(text)
        except ValueError:
            return None

    @field_validator(
        "company",
        "product",
        "seller",
        "seller_url",
        "risk",
        "verdicts",
        "verified_contradicted",
        "recommendation",
        "notes",
        mode="before",
    )
    @classmethod
    def _blank(cls, value):
        return "" if value is None else str(value)

    @field_validator("meets_reqs", mode="before")
    @classmethod
    def _meets(cls, value):
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "yes", "pass", "ok", "✅", "1"}:
            return True
        if text in {"false", "no", "fail", "❌", "0"}:
            return False
        return None


class ParsedFindings(BaseModel):
    problem: str = ""
    must_haves: str = ""
    budget: str = ""
    candidates: list[Candidate] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class Target(BaseModel):
    company: str
    domain: str | None = None
    products: list[str] = Field(default_factory=list)
    kind: str | None = None  # hardware | software
    verdicts: str = ""
    score: float | None = None
    meets_reqs: bool | None = None
    role: str = ""  # manufacturer | seller
    risk: str = ""
    recommendation: str = ""


class OutreachInput(BaseModel):
    sender: Sender
    targets: list[Target]


class Person(BaseModel):
    name: str
    title: str = ""
    why_reach_out: str = ""
    company: str = ""
    linkedin: str | None = None
    email: str | None = None
    source_url: str = ""
    source_note: str = ""


class DraftEmail(BaseModel):
    to_name: str
    to_title: str
    subject: str
    body: str


class CompanyOutreach(BaseModel):
    company: str
    domain: str | None = None
    products: list[str] = Field(default_factory=list)
    role: str = ""
    risk: str = ""
    people: list[Person] = Field(default_factory=list)
    emails: list[DraftEmail] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class OutreachPack(BaseModel):
    sender: Sender
    report: str = ""
    findings: ParsedFindings | None = None
    companies: list[CompanyOutreach]
