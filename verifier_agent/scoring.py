"""Candidate scoring (spec 4.3). Pure code, no LLM.

score = 0.5 * requirement_fit + 0.3 * verification_ratio + 0.2 * vendor_trust

- requirement_fit: share of must-haves (plus the budget, when one is set) marked "meets" by the
  Catalog reader; "unknown" counts as not met. Any must-have "fails", or price over budget,
  -> meets_requirements=False and the candidate is ranked after all others.
- verification_ratio: (verified - contradicted) / claims checked, floored at 0.
- vendor_trust: low risk 1.0, medium 0.5, high 0.0.
"""
from __future__ import annotations

import config
from models import CandidateProfile, ClaimVerdict, RequirementsChecklist, VerifiedCandidate

TRUST = {"low": 1.0, "medium": 0.5, "high": 0.0}


def requirement_fit(profile: CandidateProfile, checklist: RequirementsChecklist) -> tuple[float, bool]:
    """Return (share of hard constraints met, meets_requirements)."""
    keys = [r.field for r in checklist.must_have]
    if checklist.budget_usd is not None:
        keys.append("budget_usd")
    if not keys:
        return 1.0, True
    fits = [profile.requirement_fit.get(k, "unknown") for k in keys]
    return fits.count("meets") / len(fits), "fails" not in fits


def verification_ratio(verdicts: list[ClaimVerdict]) -> float:
    if not verdicts:
        return 0.0
    v = sum(x.verdict == "verified" for x in verdicts)
    c = sum(x.verdict == "contradicted" for x in verdicts)
    return max(0.0, (v - c) / len(verdicts))


def breakdown(profile: CandidateProfile, checklist: RequirementsChecklist, verdicts: list[ClaimVerdict],
              vendor_risk: str) -> dict[str, float]:
    """The three score components (0..1 each) and their weighted total."""
    fit, _ = requirement_fit(profile, checklist)
    ver, trust = verification_ratio(verdicts), TRUST.get(vendor_risk, 0.5)
    total = config.W_FIT * fit + config.W_VERIFY * ver + config.W_TRUST * trust
    return {"fit": round(fit, 3), "verification": round(ver, 3), "trust": trust, "total": round(total, 3)}


def score(profile: CandidateProfile, checklist: RequirementsChecklist, verdicts: list[ClaimVerdict],
          vendor_risk: str) -> tuple[float, bool]:
    _, meets = requirement_fit(profile, checklist)
    return breakdown(profile, checklist, verdicts, vendor_risk)["total"], meets


def rank(candidates: list[VerifiedCandidate]) -> list[VerifiedCandidate]:
    """Candidates meeting requirements first, each group by score descending."""
    return sorted(candidates, key=lambda c: (not c.meets_requirements, -c.score))
