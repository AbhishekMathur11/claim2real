#!/usr/bin/env python3
"""Fill a RequirementsChecklist JSON from a problem statement via Anthropic."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

from config import CANONICAL_FIELDS
from models import Constraint, SystemPlan, parse_bundle, parse_plan

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
API_KEY_RE = re.compile(r"sk-ant-(?:api|oat|usr)[A-Za-z0-9_-]+")


def _yaml_key() -> str:
    path = ROOT / "api.yaml"
    if not path.exists():
        return ""
    blob = path.read_text()
    try:
        data = yaml.safe_load(blob) or {}
    except yaml.YAMLError:
        data = {}
    if isinstance(data, dict):
        anthropic = data.get("anthropic")
        if isinstance(anthropic, dict):
            key = str(anthropic.get("api_key") or anthropic.get("key") or "").strip()
            if key:
                return key
        if isinstance(data.get("ANTHROPIC_API_KEY"), str):
            return data["ANTHROPIC_API_KEY"].strip()
    match = API_KEY_RE.search(blob)
    return match.group(0) if match else ""


def _cli_token() -> str:
    try:
        raw = subprocess.check_output(
            ["ant", "auth", "print-credentials"],
            text=True,
            timeout=30,
        )
        data = json.loads(raw)
    except Exception:
        return ""
    return str(data.get("access_token") or "").strip()


def api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    yaml_key = _yaml_key()
    if yaml_key.startswith("sk-ant-api"):
        return yaml_key
    cli = _cli_token()
    if cli:
        return cli
    if yaml_key:
        return yaml_key
    sys.exit(
        "No Anthropic credentials. Run `ant auth login`, or put an API key in "
        "api.yaml / ANTHROPIC_API_KEY (console.anthropic.com/settings/keys)."
    )


def client() -> Anthropic:
    secret = api_key()
    if secret.startswith("sk-ant-oat"):
        return Anthropic(auth_token=secret, timeout=90.0)
    return Anthropic(api_key=secret, timeout=90.0)


def _prompt_text(name: str) -> str:
    return (ROOT / "prompts" / name).read_text()


def _fields_block() -> str:
    numeric = [f"{name} ({unit})" for name, unit in CANONICAL_FIELDS.items() if unit]
    categorical = [name for name, unit in CANONICAL_FIELDS.items() if unit is None]
    return (
        "Numeric (bare number): " + ", ".join(numeric) + "\n"
        "Categorical (operator has, unit null): " + ", ".join(categorical)
    )


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_objects(raw: str) -> list[dict]:
    decoder = json.JSONDecoder()
    items = []
    idx = 0
    while True:
        start = raw.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(raw, start)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            items.append(obj)
        idx = end
    return items


def _loads_json(text: str) -> dict:
    raw = _strip_fence(text)
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
        except json.JSONDecodeError:
            objects = _extract_objects(raw)
            checklists = [
                item
                for item in objects
                if item.get("component_type") and (item.get("must_have") or item.get("search_terms"))
            ]
            if not checklists:
                raise
            data = {"checklists": checklists}
    if not isinstance(data, dict):
        raise json.JSONDecodeError("expected a JSON object", raw, 0)
    return data


def _chat(messages: list[dict], model: str, max_tokens: int) -> dict:
    system = "\n\n".join(
        m["content"] for m in messages if m.get("role") == "system" and m.get("content")
    )
    chat = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in {"user", "assistant"}
    ]
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        messages=chat,
        output_config={
            "effort": "low",
            "format": {
                "type": "json_schema",
                "schema": {"type": "object", "additionalProperties": True},
            },
        },
    )
    if system:
        kwargs["system"] = system
    try:
        response = client().messages.create(**kwargs)
    except Exception:
        kwargs["output_config"] = {"effort": "low"}
        try:
            response = client().messages.create(**kwargs)
        except Exception:
            kwargs.pop("output_config", None)
            response = client().messages.create(**kwargs)
    raw = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", "") == "text"
    )
    if not raw:
        raise SystemExit("Model returned empty JSON.")
    try:
        return _loads_json(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"RequirementsChecklist invalid JSON:\n{exc}\n{raw}") from exc


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


LEQ_FIELDS = {
    "depth_accuracy_mm",
    "repeatability_mm",
    "mass_kg",
    "angular_resolution_deg",
    "operating_temp_max_c",
    "localization_accuracy_mm",
}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _first_number(raw) -> float | None:
    """First number in a value like 40, "40 Nm", "$4,000" or "about 12 kg"."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    m = _NUMBER.search(re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(raw)))
    return float(m.group()) if m else None


def _clean_row(item: dict, dropped: list[str] | None = None) -> dict | None:
    """Repair one LLM constraint row, or drop it (noted in `dropped`) when it cannot be made valid.

    The model sometimes leaves value null, writes "40 Nm" for a number, or uses "has" on a numeric
    field. One bad row used to fail the whole spec; now only that row is lost.
    """
    field = str(item.get("field") or "").strip()
    value = item.get("value")
    if isinstance(value, dict) and "value" in value:  # model nested the row: {"operator": .., "value": ..}
        item = {**item, "operator": value.get("operator", item.get("operator"))}
        value = value["value"]
    if field not in CANONICAL_FIELDS:
        reason = "unknown field"
    elif value is None or (isinstance(value, str) and not value.strip()) or value == []:
        reason = "no value given"
    else:
        unit = CANONICAL_FIELDS[field]
        if unit is None:  # categorical
            row = {"field": field, "operator": "has",
                   "value": ", ".join(map(str, value)) if isinstance(value, list) else str(value).strip(), "unit": None}
        else:
            number = _first_number(value)
            if number is None:
                row, reason = None, f"non-numeric value {value!r}"
            else:
                op = item.get("operator")
                if op not in (">=", "<=", "=="):
                    op = "<=" if field in LEQ_FIELDS else ">="
                row = {"field": field, "operator": op, "value": int(number) if number.is_integer() else number,
                       "unit": unit}
        if row is not None:
            try:
                return Constraint.model_validate(row).model_dump()
            except Exception as exc:  # noqa: BLE001
                reason = str(exc).splitlines()[-1][:80]
    if dropped is not None and field:
        dropped.append(f"Dropped constraint {field} ({reason})")
    return None


def _as_constraints(value, dropped: list[str] | None = None) -> list[dict]:
    if not value:
        return []
    if isinstance(value, list):
        rows = []
        for item in value:
            if isinstance(item, dict) and "field" in item:
                rows.append(_clean_row(item, dropped))
            elif isinstance(item, str) and ":" in item:
                field, raw = item.split(":", 1)
                rows.append(_constraint(field.strip(), raw.strip()))
        return [row for row in rows if row]
    if isinstance(value, dict):
        return [
            row
            for field, raw in value.items()
            if (row := _constraint(str(field), raw))
        ]
    return []


def _constraint(field: str, raw) -> dict | None:
    if field not in CANONICAL_FIELDS:
        return None
    unit = CANONICAL_FIELDS[field]
    if unit is None:
        return {"field": field, "operator": "has", "value": str(raw), "unit": None}
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        number = int(number)
    operator = "<=" if field in LEQ_FIELDS else ">="
    return {"field": field, "operator": operator, "value": number, "unit": unit}


def _default_constraints(name: str) -> list[dict]:
    n = name.lower()
    if any(word in n for word in ("camera", "rgb", "depth", "vision")):
        rows = [("sensing_modality", "RGB-D"), ("working_distance_mm", 400), ("frame_rate_hz", 15)]
        if any(word in n for word in ("3d", "depth", "rgb-d")):
            rows.append(("depth_accuracy_mm", 2))
    elif any(word in n for word in ("arm", "manipulator", "gantry")):
        rows = [("payload_kg", 5), ("reach_mm", 850), ("repeatability_mm", 0.1)]
    elif any(word in n for word in ("gripper", "vacuum", "end effector")):
        rows = [("gripper_type", "parallel"), ("grip_force_n", 50)]
    elif any(word in n for word in ("lidar", "scanner", "safety")):
        rows = [("lidar_range_mm", 20000), ("angular_resolution_deg", 0.25), ("frame_rate_hz", 15)]
    elif any(word in n for word in ("mobile", "amr", "agv", "base")):
        rows = [("locomotion", "differential"), ("max_speed_mm_s", 1000), ("runtime_h", 8), ("localization_accuracy_mm", 20)]
    elif any(word in n for word in ("compute", "ipc", "gpu")):
        rows = [("compute_tops", 50), ("memory_gb", 16), ("comm_interface", "Ethernet")]
    elif any(word in n for word in ("force", "torque", "tactile")):
        rows = [("comm_interface", "EtherCAT")]
    else:
        rows = [("comm_interface", "Ethernet")]
    return [row for field, raw in rows if (row := _constraint(field, raw))]


def _coerce_checklist(item: dict) -> dict:
    name = str(item.get("component_type") or "component")
    terms = _as_list(item.get("search_terms"))
    if len(terms) < 3:
        terms = (terms + [name, f"{name} supplier", f"industrial {name}"])[:6]
    dropped: list[str] = []
    must_have = _as_constraints(item.get("must_have"), dropped)
    if not must_have:
        must_have = _default_constraints(name)
        dropped.append(f"No usable must-have constraints from the model; used defaults for {name}")
    nice = _as_constraints(item.get("nice_to_have"), dropped)
    keep = {
        "problem_statement": item.get("problem_statement") or "",
        "component_type": name,
        "search_terms": terms[:6],
        "software": [str(x) for x in _as_list(item.get("software"))],
        "must_have": must_have,
        "nice_to_have": nice,
        "assumptions": [str(x) for x in _as_list(item.get("assumptions"))] + dropped,
    }
    for key, kind in (("budget_usd", float), ("max_lead_time_days", int), ("quantity", int)):
        number = _first_number(item.get(key))
        if key == "max_lead_time_days" and number and "week" in str(item.get(key)).lower():
            number *= 7
        if number is not None and number > 0:
            keep[key] = kind(number)
    if isinstance(item.get("ship_to"), str) and item["ship_to"].strip():
        keep["ship_to"] = item["ship_to"].strip()
    return keep


def _normalize_spec(data: dict) -> dict:
    if isinstance(data.get("checklists"), dict):
        data["checklists"] = list(data["checklists"].values())
    if not isinstance(data.get("checklists"), list):
        for key in ("checklist", "specs", "requirements"):
            if isinstance(data.get(key), list):
                data["checklists"] = data[key]
                break
    hardware = data.get("hardware")
    if not isinstance(data.get("checklists"), list):
        if (
            isinstance(hardware, list)
            and hardware
            and isinstance(hardware[0], dict)
            and ("must_have" in hardware[0] or "component_type" in hardware[0])
        ):
            data["checklists"] = hardware
            data["hardware"] = [h.get("component_type", "") for h in hardware]
        elif "component_type" in data:
            data["checklists"] = [
                {k: v for k, v in data.items() if k not in {"hardware", "software", "checklists"}}
            ]
    if isinstance(data.get("checklists"), list):
        data["checklists"] = [
            _coerce_checklist(item) for item in data["checklists"] if isinstance(item, dict)
        ]
    return data


def _missing_hardware(plan: SystemPlan, component_types: list[str]) -> list[str]:
    blobs = [_norm(name) for name in component_types]
    missing = []
    for item in plan.hardware:
        token = _norm(item.component_type)
        if not any(token in blob or blob in token for blob in blobs):
            missing.append(item.component_type)
    return missing


def decompose(problem: str, model: str) -> SystemPlan:
    data = _chat(
        [
            {"role": "system", "content": _prompt_text("decompose.md")},
            {
                "role": "user",
                "content": (
                    "Problem statement:\n"
                    f"{problem}\n\n"
                    "Walk every category. Include implied hardware the user did not name. Keep why to one short sentence. JSON only, no markdown."
                ),
            },
        ],
        model,
        max_tokens=4096,
    )
    if isinstance(data.get("hardware"), list):
        data["hardware"] = data["hardware"][:6]
    return parse_plan(data)


def specify(
    problem: str,
    plan: SystemPlan,
    model: str,
    *,
    spec: str | None = None,
    refine: str | None = None,
    extra: str = "",
) -> dict:
    def one(item) -> dict:
        user = (
            f"Fields:\n{_fields_block()}\n\n"
            f"Problem:\n{problem}\n\n"
            f"Specify this ONE hardware item. Return one checklist object, not a bundle.\n"
            f"{json.dumps(item.model_dump(), separators=(',', ':'))}\n"
            "Keys: component_type, search_terms, software, must_have, nice_to_have, "
            "budget_usd, max_lead_time_days, assumptions. No markdown. No other components.\n"
        )
        if spec and refine:
            user += f"\nCurrent output:\n{spec.strip()}\n\nRevision notes:\n{refine.strip()}\n"
        if extra:
            user += f"\n{extra}\n"
        data = _chat(
            [
                {"role": "system", "content": _prompt_text("system.md")},
                {"role": "user", "content": user},
            ],
            model,
            max_tokens=4096,
        )
        if isinstance(data.get("checklists"), list) and data["checklists"]:
            first = data["checklists"][0]
            if isinstance(first, dict):
                data = first
        data["component_type"] = item.component_type
        if not data.get("software"):
            data["software"] = item.software
        return data

    # One Claude call per hardware item, run in parallel (order preserved by map).
    with ThreadPoolExecutor(max_workers=max(1, len(plan.hardware))) as pool:
        checklists = list(pool.map(one, plan.hardware))
    return {
        "hardware": [item.component_type for item in plan.hardware],
        "software": plan.software,
        "checklists": checklists,
    }


def generate_spec(
    problem: str,
    *,
    spec: str | None = None,
    refine: str | None = None,
    model: str = DEFAULT_MODEL,
) -> str:
    problem = problem.strip()
    plan = decompose(problem, model)
    data = _normalize_spec(specify(problem, plan, model, spec=spec, refine=refine))
    if not isinstance(data.get("checklists"), list):
        data = _normalize_spec(
            specify(
                problem,
                plan,
                model,
                spec=spec,
                refine=refine,
                extra="Output MUST include checklists: an array with one object per locked hardware item.",
            )
        )
    data["hardware"] = [item.component_type for item in plan.hardware]
    data["software"] = plan.software
    bundle = parse_bundle(data, problem)
    dropped = _missing_hardware(plan, [c.component_type for c in bundle.checklists])
    if dropped:
        data = _normalize_spec(
            specify(
                problem,
                plan,
                model,
                spec=spec,
                refine=refine,
                extra=f"You dropped hardware: {dropped}. Include every locked plan item as its own checklist.",
            )
        )
        data["hardware"] = [item.component_type for item in plan.hardware]
        data["software"] = plan.software
        bundle = parse_bundle(data, problem)
        dropped = _missing_hardware(plan, [c.component_type for c in bundle.checklists])
        if dropped:
            raise SystemExit(
                "RequirementsChecklist invalid: missing hardware from plan: "
                + ", ".join(dropped)
            )
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
