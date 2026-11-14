"""Unit normalization to canonical units (requirements_agent CANONICAL_FIELDS) and fit checks."""
from __future__ import annotations

import re

import config

# canonical unit -> {accepted unit spelling (normalized): factor to canonical}
_FACTORS: dict[str, dict[str, float]] = {
    "N·m": {"nm": 1, "n·m": 1, "n.m": 1, "n-m": 1, "newtonmeter": 1, "newtonmeters": 1, "mnm": 0.001,
            "kgf·cm": 0.0980665, "kgfcm": 0.0980665, "kg·cm": 0.0980665, "kgcm": 0.0980665, "kg-cm": 0.0980665,
            "oz·in": 0.00706155, "ozin": 0.00706155, "oz-in": 0.00706155, "lbf·in": 0.112985, "lbin": 0.112985,
            "lb-in": 0.112985, "lbf·ft": 1.35582, "lbft": 1.35582, "lb-ft": 1.35582, "ft-lb": 1.35582},
    "kg": {"kg": 1, "g": 0.001, "gram": 0.001, "grams": 0.001, "lb": 0.453592, "lbs": 0.453592, "oz": 0.0283495},
    "mm": {"mm": 1, "cm": 10, "m": 1000, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4, "µm": 0.001, "um": 0.001},
    "V": {"v": 1, "vdc": 1, "volt": 1, "volts": 1, "kv": 1000},
    "W": {"w": 1, "kw": 1000, "watt": 1, "watts": 1, "hp": 745.7},
    "A": {"a": 1, "ma": 0.001, "amp": 1, "amps": 1},
    "rpm": {"rpm": 1, "r/min": 1, "rev/min": 1},
    "Hz": {"hz": 1, "khz": 1000, "fps": 1},
    "N": {"n": 1, "kn": 1000, "kgf": 9.80665, "lbf": 4.44822},
    "°": {"°": 1, "deg": 1, "degree": 1, "degrees": 1, "arcmin": 1 / 60, "arcsec": 1 / 3600},
    "mm/s": {"mm/s": 1, "m/s": 1000, "cm/s": 10},
    "h": {"h": 1, "hr": 1, "hrs": 1, "hour": 1, "hours": 1, "min": 1 / 60},
    "TOPS": {"tops": 1},
    "GB": {"gb": 1, "mb": 1 / 1024, "tb": 1024},
}


def _norm_unit(u: str) -> str:
    u = u.strip().lower().replace("⋅", "·").replace("*", "·").replace(" ", "")
    return u.replace("newton·meter", "nm").replace("newton·metre", "nm")


def to_canonical(field: str, value: float | int | str, unit: str | None) -> tuple[float | str, str | None] | None:
    """Convert a claim to the field's canonical unit. Returns None if it cannot be converted."""
    canon = config.CANONICAL_FIELDS.get(field)
    if canon is None:  # categorical or unknown field: keep as text
        return (str(value), None)
    num = parse_number(value)
    if num is None:
        return None
    if canon == "°C":
        u = _norm_unit(unit or "°c")
        if u in ("°f", "f", "degf"):
            return (round((num - 32) * 5 / 9, 3), canon)
        return (num, canon) if u in ("°c", "c", "degc") else None
    if not unit:
        return (num, canon)  # assume canonical when the page gives no unit
    u = _norm_unit(unit)
    table = _FACTORS.get(canon, {})
    if u == _norm_unit(canon) or u in table:
        return (round(num * table.get(u, 1), 6), canon)
    return None


def parse_number(value: float | int | str) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(value))
    return float(m.group(0).replace(",", "")) if m else None


def to_usd(amount: float | None, currency: str | None) -> float | None:
    if amount is None:
        return None
    rate = config.FX_TO_USD.get((currency or "USD").upper().strip("$ "))
    return round(amount * rate, 2) if rate else None


def check(operator: str, required: float | int | str, actual: float | str) -> bool:
    """Does `actual` satisfy `operator required`? Values must already be in the same unit."""
    if operator == "has":
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(str(required).lower()), str(actual).lower()))
    a, r = parse_number(actual), parse_number(required)
    if a is None or r is None:
        return False
    if operator == ">=":
        return a >= r
    if operator == "<=":
        return a <= r
    return abs(a - r) <= 1e-6 * max(1.0, abs(r))
