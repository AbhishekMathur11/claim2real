"""Offline test of the discovery pipeline: Telem and the LLM are mocked."""
from pathlib import Path
from unittest.mock import MagicMock

from telem.models import ProviderRun, SearchResponse, SearchResult

import llm
import discovery
from models import load_checklists
from telem_client import TelemRun

FIX = Path(__file__).parent.parent / "fixtures"
CHECKLIST = load_checklists(FIX / "actuator_checklist.json")[0]


def _resp(queries, sid="sess-1"):
    runs = []
    for i, q in enumerate(queries):
        for prov in ("exa", "brave"):
            runs.append(ProviderRun(provider=prov, status="completed", latency_ms=300, query=q, batch_index=i,
                results=[
                    SearchResult(url=f"https://www.vendor{i}.com/actuator-x{i}?ref={prov}", title=f"Actuator X{i}",
                                 summary="12 Nm continuous, CAN, 0.9 kg", provider=prov),
                    SearchResult(url="https://shop.cubemars.co.uk/ak80-9/", title="AK80-9 KV100",
                                 summary="CubeMars AK80-9 9 Nm rated", provider=prov),
                ]))
    return SearchResponse(results=[], by_provider=runs, session_id=sid, interaction_id="i", status="completed")


def _fake_client(calls):
    client = MagicMock()
    def fake_search(q, **kw):
        calls.append(kw)
        return _resp(q if isinstance(q, list) else [q])
    client.search.side_effect = fake_search
    return client


def test_discover(monkeypatch):
    calls = []
    client = _fake_client(calls)

    def fake_llm(system, user, schema, max_tokens=0):
        if schema is discovery.QueryPlan:
            return schema(queries=[{"query": "CAN joint actuator 10 Nm", "angle": "spec"},
                                   {"query": "harmonic drive actuator under $500", "angle": "budget"}])
        return schema(picks=[{"index": 0, "name": "AK80-9", "vendor": "CubeMars", "reason": "r"},
                             {"index": 99, "name": "bogus", "vendor": "x", "reason": "r"}])
    monkeypatch.setattr(llm, "call_json", fake_llm)

    run = TelemRun(client=client)
    cands = discovery.discover(CHECKLIST, run)

    # 3 calls: open-web, recency, distributor; first opens session with goal, rest reuse it
    assert len(calls) == 3
    assert "goal" in calls[0] and "session" not in calls[0]
    assert all(c["session"] == "sess-1" and "goal" not in c for c in calls[1:])
    assert "published_after" in calls[1] and "include_domains" in calls[2]
    assert all(c["auto_routing"] == "accuracy" for c in calls)
    # every angle covered after fallback top-up
    assert {q.angle for q in run.discovery_plans[CHECKLIST.component_type]} == set(discovery.ANGLES)
    # invalid index dropped; provider attribution merged
    assert len(cands) == 1 and cands[0].vendor_domain == "cubemars.co.uk"
    assert cands[0].found_by_provider == "exa, brave"
    assert run.session_id == "sess-1" and len(run.traces) > 0
    assert cands[0].component_type == "robot joint actuator"
    assert "robot joint actuator" in calls[0]["context"]


def test_bundle_one_session(monkeypatch):
    """Multi-component bundle: goal sent once, every later call reuses the session."""
    calls = []
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no LLM")))
    checklists = load_checklists(FIX / "bin_picking_bundle.json")
    run = TelemRun(client=_fake_client(calls))
    out = discovery.discover_all(checklists, run, n=3)
    assert list(out) == ["3D depth camera", "robot arm"]
    assert sum("goal" in c for c in calls) == 1 and "goal" in calls[0]
    assert all(c.get("session") == "sess-1" for c in calls[1:])
    # LLM down -> deterministic plan + ranking fallback still yields candidates
    assert all(len(v) == 3 for v in out.values())


def test_canonical_url_dedupes_query_and_www():
    a = discovery.canonical_url("https://www.x.com/p/1/?ref=a")
    b = discovery.canonical_url("http://x.com/p/1")
    assert a == b


def test_page_kind_prefers_products():
    H = discovery.Hit
    blog = H(url="https://dev.to/x/how-to-select", title="", snippet="", domain="dev.to")
    blog2 = H(url="https://openelab.io/blogs/learn/x", title="", snippet="", domain="openelab.io")
    prod = H(url="https://www.robotshop.com/products/ak40", title="", snippet="", domain="robotshop.com")
    assert discovery.page_kind_score(prod) > 0 > discovery.page_kind_score(blog)
    assert discovery.page_kind_score(blog2) < 0
