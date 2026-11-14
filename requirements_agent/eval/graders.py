"""Checks a bundle of RequirementsChecklist objects."""

from __future__ import annotations

import json

from pydantic import ValidationError

from models import RequirementsBundle, RequirementsChecklist


def grade(spec: str, case: dict) -> list[dict]:
    try:
        data = json.loads(spec)
        if "checklists" in data:
            bundle = RequirementsBundle.model_validate(data)
        else:
            bundle = RequirementsBundle(
                checklists=[RequirementsChecklist.model_validate(data)]
            )
        schema_ok, schema_detail = True, f"{len(bundle.checklists)} checklist(s)"
    except (json.JSONDecodeError, ValidationError) as exc:
        bundle = None
        schema_ok, schema_detail = False, str(exc).split("\n")[0]

    checklists = list(bundle.checklists) if bundle else []
    terms_ok = all(3 <= len(c.search_terms) <= 6 for c in checklists) and bool(checklists)
    must = [item for c in checklists for item in c.must_have]
    constraints = must + [item for c in checklists for item in c.nice_to_have]
    fields = {item.field for item in constraints}
    missing = [f for f in case.get("require_fields", []) if f not in fields]
    mins = case.get("require_min", {})
    short = []
    for field, floor in mins.items():
        hit = next((c for c in constraints if c.field == field), None)
        if hit is None or not isinstance(hit.value, (int, float)) or hit.value < floor:
            short.append(f"{field}>={floor}")
    blob = " ".join(
        f"{c.component_type} {' '.join(c.search_terms)}" for c in checklists
    ).lower()
    missing_types = [t for t in case.get("require_types", []) if t.lower() not in blob]
    any_miss = [
        "|".join(group)
        for group in case.get("require_any", [])
        if not any(token.lower() in blob for token in group)
    ]
    min_n = int(case.get("min_checklists", 1))

    return [
        {"name": "schema", "ok": schema_ok, "detail": schema_detail},
        {
            "name": "search_terms",
            "ok": terms_ok,
            "detail": str([c.search_terms for c in checklists]) if checklists else "none",
        },
        {
            "name": "split",
            "ok": len(checklists) >= min_n,
            "detail": f"{len(checklists)}/{min_n}",
        },
        {
            "name": "required_types",
            "ok": not missing_types and not any_miss,
            "detail": ", ".join(missing_types + any_miss) or "hit",
        },
        {
            "name": "required_fields",
            "ok": not missing,
            "detail": ", ".join(missing) or "hit",
        },
        {
            "name": "required_mins",
            "ok": not short,
            "detail": ", ".join(short) or "hit",
        },
    ]
