"""Offline tests for the Verifier and scoring: AsyncTelem, Tavily and the LLM are mocked."""
from pathlib import Path

from telem.models import ProviderRun, SearchResponse, SearchResult

import llm
import scoring
import tavily_client
import telem_client
import verifier
from models import Candidate, CandidateProfile, Claim, ClaimVerdict, load_checklists
from telem_client import TelemRun

CHECK = load_checklists(Path(__file__).parent.parent / "fixtures/actuator_checklist.json")[0]
URL = "https://www.robotshop.com/products/cubemars-ak80-9"


def profile(fit=None, price=429.0, contact="sales@cubemars.com"):
    cand = Candidate(name="CubeMars AK80-9 KV100", vendor="CubeMars", url=URL, vendor_domain="robotshop.com",
                     found_by_provider="exa", found_by_query="q", reason="r", component_type=CHECK.component_type)
    claims = [Claim(field="continuous_torque_nm", value=9.0, unit="N·m", quote="Rated torque: 9 N.m", source_url=URL),
              Claim(field="mass_kg", value=0.485, unit="kg", quote="Weight: 485 g", source_url=URL),
              Claim(field="comm_interface", value="CAN bus", unit=None, quote="Communication: CAN bus", source_url=URL)]
    return CandidateProfile(candidate=cand, claims=claims, price_usd=price, price_quote="Price: $429.00",
                            availability="In stock", contact=contact, product_name="AK80-9 KV100",
                            requirement_fit=fit or {"continuous_torque_nm": "fails", "mass_kg": "meets",
                                                    "comm_interface": "meets", "budget_usd": "meets"})


EVIDENCE = [  # (provider, url, title, summary)
    ("exa", "https://www.robotshop.com/x/ak80-9", "AK80-9 at RobotShop", "AK80-9 rated torque 9 Nm"),      # seller: dropped
    ("exa", "https://www.cubemars.com/ak80-9.html", "AK80-9 official", "AK80-9 rated torque 9 Nm"),        # vendor: dropped
    ("brave", "https://store.example-a.com/ak80-9", "AK80-9 KV100 actuator", "AK80-9 rated torque 9 Nm, 485 g"),
    ("you", "https://wiki.example-b.org/ak80-9", "AK80-9 review", "AK80-9 continuous torque 9 Nm peak 18 Nm"),
    ("you", "https://forum.example-c.net/t/1", "AK80-9 weight", "My AK80-9 weighs 520 g, not 485 g"),
]


class FakeAsync:
    def __init__(self): self.calls = []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def search(self, q, **kw):
        self.calls.append((q, kw))
        runs = [ProviderRun(provider=p, status="succeeded", query=q[0], batch_index=0,
                            results=[SearchResult(url=u, title=t, summary=s, provider=p)]) for p, u, t, s in EVIDENCE]
        return SearchResponse(by_provider=runs, session_id="s1", interaction_id="i", status="succeeded")


def setup(monkeypatch, judge):
    fake = FakeAsync()
    monkeypatch.setattr(verifier, "async_client", lambda: fake)
    monkeypatch.setattr(tavily_client, "search", lambda q, tr, st, n=5: [
        {"url": "https://datasheets.example-d.com/ak80-9.pdf", "title": "AK80-9 datasheet", "content": "AK80-9 rated 9 Nm"}])
    monkeypatch.setattr(llm, "call_json", judge)
    monkeypatch.setattr(verifier.config, "VERIFY_DOMAIN_AGE", False)  # no RDAP network calls offline
    return fake


def test_verify_enforces_rules(monkeypatch):
    seen = {}
    def judge(system, user, schema, max_tokens=0):
        seen["prompt"] = user
        return schema(claims=[
            {"claim_index": 0, "verdict": "verified", "supporting": [0, 1], "note": "two sources say 9 Nm"},
            {"claim_index": 1, "verdict": "contradicted", "contradicting": [99], "note": "bad index"},
            {"claim_index": 2, "verdict": "verified", "supporting": [0], "note": "one source only"},
            {"claim_index": 3, "verdict": "contradicted", "contradicting": [2], "note": "forum says 520 g"},
        ], vendor_risk="low", vendor_risk_reason="Established manufacturer.")
    fake = setup(monkeypatch, judge)
    run = TelemRun(session_id="s1")
    [v] = verifier.verify([profile()], CHECK, run)

    assert len(fake.calls) == 2  # claims batch + vendor-background/deployment batch
    q, kw = fake.calls[0]
    bg_q, bg_kw = fake.calls[1]
    assert bg_kw["session"] == "s1" and any("founded" in x for x in bg_q) and any("github" in x for x in bg_q)
    assert kw["session"] == "s1" and kw["max_routing_providers"] == 3 and kw["auto_routing"] == "accuracy"
    assert any("reviews complaints" in x for x in q)
    # seller (robotshop) and vendor (cubemars) domains never reach the judge
    assert "robotshop.com" not in seen["prompt"].split("Evidence:")[1]
    assert "cubemars.com |" not in seen["prompt"]
    verdicts = [cv.verdict for cv in v.verdicts]
    assert len(v.verdicts) == 4  # 3 must-haves + price, capped at 4
    assert verdicts[0] == "verified"            # 2 independent domains
    assert verdicts[1] == "unverified"          # contradicted but cited index invalid
    assert verdicts[2] == "unverified"          # verified with one domain -> downgraded
    assert verdicts[3] == "contradicted"
    engines = {e.engine for cv in v.verdicts for e in cv.evidence}
    assert "tavily" in engines and any(e.startswith("telem:") for e in engines)  # both engines cited
    assert v.vendor_risk == "low" and v.meets_requirements is False   # torque fails a must-have
    assert sum(t.stage == "verifier" and t.kind == "search" for t in run.traces) == 2 * len(EVIDENCE)
    # report fields: every criterion present, unrated ones are "unknown"
    assert [c.criterion for c in v.vendor_profile.criteria] == list(verifier.VENDOR_CRITERIA)
    assert v.score_breakdown["total"] == v.score


def test_report_fields_and_render(monkeypatch):
    def judge(system, user, schema, max_tokens=0):
        assert "Vendor criteria to rate" in user and "Registry facts" in user
        return schema(
            claims=[{"claim_index": 0, "verdict": "verified", "supporting": [0, 1], "note": "9 Nm",
                     "independent_value": "9 N·m rated, 18 N·m peak"}],
            vendor_risk="low", vendor_risk_reason="Established.", business_type="manufacturer",
            founded_year=2016, founded_evidence=[0],
            criteria=[{"criterion": "Time in market", "rating": "positive", "detail": "Founded 2016.", "evidence": [0]},
                      {"criterion": "Price consistency", "rating": "neutral", "detail": "In line.", "evidence": [99]}],
            release_year=2021, release_evidence=[1], deployment_level="some real-world use",
            deployment=[{"kind": "forum discussion", "summary": "User weighed it.", "evidence": 2},
                        {"kind": "project/build", "summary": "bad index", "evidence": 99}],
            technical_summary="Specs match.", commercial_summary="Known seller.", recommendation="Buy.")
    setup(monkeypatch, judge)
    old = verifier.domain_age.DomainAge(domain="robotshop.com", registered=verifier.date(2025, 12, 1), source_url="u")
    monkeypatch.setattr(verifier, "_lookup_age", lambda d: _coro(old))
    [v] = verifier.verify([profile()], CHECK, TelemRun(session_id="s1"))
    vp, m = v.vendor_profile, v.maturity
    assert v.verdicts[0].independent_value == "9 N·m rated, 18 N·m peak"
    assert vp.founded_year == 2016 and vp.business_type == "manufacturer" and vp.domain_registered == "2025-12-01"
    crit = {c.criterion: c for c in vp.criteria}
    assert crit["Time in market"].rating == "concern"          # young domain overrides the LLM's "positive"
    assert any(s.domain == "rdap.org" for s in crit["Time in market"].sources)
    assert crit["Price consistency"].sources == []             # invalid index dropped
    assert m.release_year == 2021 and len(m.deployment) == 1   # deployment item with a bad index dropped
    assert any("registered only" in r for r in [v.vendor_risk_reason]) and v.vendor_risk == "medium"
    md = verifier.report.render({CHECK.component_type: [v]}, {CHECK.component_type: CHECK}, "s1", [],
                                verifier.CRITERIA_HELP)
    for text in ("How candidates were judged", "9 N·m rated, 18 N·m peak", "Time in market", "⚠️ concern",
                 "forum discussion", "Score breakdown", "Recommendation:** Buy."):
        assert text in md


async def _coro(x):
    return x


def test_llm_down_uses_rule_based(monkeypatch):
    setup(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("402")))
    [v] = verifier.verify([profile()], CHECK, TelemRun(session_id="s1"))
    torque = v.verdicts[0]
    assert torque.verdict == "verified" and len({e.domain for e in torque.evidence}) == 2
    assert v.verdicts[1].verdict == "unverified"   # 0.485 kg not stated in that form anywhere


def test_risk_signals():
    p = profile(contact="ak80seller@gmail.com")
    items = [verifier.Item(url="https://a.com", domain="a.com", title="other", text="nothing")]
    sig = verifier.code_risk_signals(p, items, {"robotshop.com"})
    assert any("free email" in s for s in sig) and any("footprint" in s for s in sig)
    assert verifier.combine_risk("low", "", sig)[0] == "high"


def test_scoring_and_rank():
    good = profile(fit={"continuous_torque_nm": "meets", "mass_kg": "meets", "comm_interface": "meets", "budget_usd": "meets"})
    v = lambda cl, x: ClaimVerdict(claim=cl, verdict=x, evidence=[])
    vs = [v(good.claims[0], "verified"), v(good.claims[1], "verified"), v(good.claims[2], "contradicted")]
    s, meets = scoring.score(good, CHECK, vs, "low")
    assert meets and s == round(0.5 * 1 + 0.3 * (1 / 3) + 0.2 * 1, 3)
    bad_s, bad_meets = scoring.score(profile(), CHECK, vs, "low")
    assert not bad_meets
    from models import VerifiedCandidate
    ranked = scoring.rank([VerifiedCandidate(profile=profile(), verdicts=[], vendor_risk="low", vendor_risk_reason="",
                                             score=0.99, meets_requirements=False),
                           VerifiedCandidate(profile=good, verdicts=[], vendor_risk="low", vendor_risk_reason="",
                                             score=0.10, meets_requirements=True)])
    assert ranked[0].meets_requirements   # meeting requirements beats a higher score


def test_contradiction_that_restates_the_value_is_rechecked():
    cl = Claim(field="continuous_torque_nm", value=40.0, unit="N·m", quote="Rated Torque | 40 Nm", source_url=URL)
    items = [verifier.Item(url=f"https://{d}/x", domain=d, title="DM-J10010", text="rated 40 Nm") for d in ("a.com", "b.com")]
    j = verifier.ClaimJudgement(claim_index=0, verdict="contradicted", contradicting=[0, 1],
                                independent_value="Nominal/rated torque 40 N·m; peak 150 N·m")
    assert verifier.enforce(cl, j, items).verdict == "verified"
    j.independent_value = "9 N·m rated, 27 N·m peak"
    assert verifier.enforce(cl, j, items).verdict == "contradicted"


def test_risk_reason_not_duplicated():
    sig = ["seller domain x.com was registered only 0.7 years ago (2026-03-11)"]
    level, reason = verifier.combine_risk("medium", "Seller domain was registered only about 0.7 years ago.", sig)
    assert level == "medium" and reason.count("registered") == 1 and ".;" not in reason
