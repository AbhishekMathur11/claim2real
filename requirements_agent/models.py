"""RequirementsChecklist — Discovery rejects anything that fails this model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from config import CANONICAL_FIELDS, FORBIDDEN_CONSTRAINT_FIELDS

Operator = Literal[">=", "<=", "==", "has"]


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    operator: Operator
    value: float | int | str
    unit: str | None = None

    @model_validator(mode="after")
    def canonical(self) -> "Constraint":
        if self.field in FORBIDDEN_CONSTRAINT_FIELDS:
            raise ValueError(
                f"{self.field} is not a constraint; use budget_usd / max_lead_time_days"
            )
        if self.field not in CANONICAL_FIELDS:
            raise ValueError(
                f"unknown field {self.field!r}; expected one of {sorted(CANONICAL_FIELDS)}"
            )
        expected = CANONICAL_FIELDS[self.field]
        if expected is None:
            if self.operator != "has":
                raise ValueError(f"{self.field} is categorical; operator must be 'has'")
            if not isinstance(self.value, str):
                raise ValueError(f"{self.field} value must be a string")
            self.unit = None
            return self
        if self.operator == "has":
            raise ValueError(f"{self.field} is numeric; use >=, <=, or ==")
        if isinstance(self.value, str):
            raise ValueError(
                f"{self.field} value must be a number in {expected}, not {self.value!r}"
            )
        self.unit = expected
        return self


class RequirementsChecklist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_statement: str
    component_type: str
    search_terms: list[str] = Field(min_length=3, max_length=6)
    must_have: list[Constraint] = Field(min_length=1)
    nice_to_have: list[Constraint] = Field(default_factory=list)
    budget_usd: float | None = None
    max_lead_time_days: int | None = None
    ship_to: str | None = None
    quantity: int = Field(default=1, ge=1)
    assumptions: list[str] = Field(default_factory=list)


class RequirementsBundle(BaseModel):
    """One or more Catalog-valid checklists. High-level jobs become several components."""

    model_config = ConfigDict(extra="ignore")

    checklists: list[RequirementsChecklist] = Field(min_length=1, max_length=6)


def parse_checklist(data: dict) -> RequirementsChecklist:
    try:
        return RequirementsChecklist.model_validate(data)
    except ValidationError as exc:
        raise SystemExit(f"RequirementsChecklist invalid:\n{exc}") from exc


def parse_bundle(data: dict, problem: str) -> RequirementsBundle:
    if "checklists" in data:
        items = data["checklists"]
    else:
        items = [data]
    if not isinstance(items, list) or not items:
        raise SystemExit("RequirementsChecklist invalid: expected checklists[]")
    stamped = []
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit("RequirementsChecklist invalid: each item must be an object")
        item = dict(item)
        item["problem_statement"] = problem
        stamped.append(parse_checklist(item))
    try:
        return RequirementsBundle(checklists=stamped)
    except ValidationError as exc:
        raise SystemExit(f"RequirementsChecklist invalid:\n{exc}") from exc
