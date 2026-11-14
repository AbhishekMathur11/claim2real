"""Offline tests: Telem, Tavily and the LLM are mocked."""
from telem.models import ProviderRun, SearchResponse, SearchResult

import llm
import software
import tavily_client
from models import SoftwareCandidate
from telem_client import TelemRun

BUNDLE = {"software": ["SLAM / localization", "grasp planning", "slam / localization"],
          "checklists": [{"problem_statement": "farm robot", "software": ["path planning"]}]}


def test_requirements_dedup_and_fallback():
    assert software.software_requirements(BUNDLE) == ["SLAM / localization", "grasp planning"]
    assert software.software_requirements({"checklists": [{"software": ["a", "b"]}, {"software": ["a"]}]}) == ["a", "b"]


class FakeAsync:
    def __init__(self, results): self.results, self.calls = results, []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def search(self, q, **kw):
        qs = q if isinstance(q, list) else [q]
        self.calls.append(kw)
        runs = [ProviderRun(provider="exa", status="ok", query=x, batch_index=i,
                            results=[SearchResult(url=u, title=t, summary=s) for u, t, s in self.results])
                for i, x in enumerate(qs)]
        return SearchResponse(by_provider=runs, session_id="s1", interaction_id="i", status="ok")


def test_discover_uses_session_and_valid_indices(monkeypatch):
    fake = FakeAsync([("https://github.com/cartographer-project/cartographer", "Cartographer", "SLAM library"),
                      ("https://slamtec.com/product", "Slamtec SDK", "commercial SLAM")])
    monkeypatch.setattr(software, "async_client", lambda: fake)
    monkeypatch.setattr(llm, "call_json", lambda s, u, schema, m=0: schema(picks=[
        {"index": 0, "name": "Cartographer", "provider": "Google", "kind": "open-source", "reason": "r"},
        {"index": 9, "name": "bogus", "provider": "x", "kind": "unknown", "reason": "r"}]))
    out = software.discover(BUNDLE, TelemRun(session_id="s1"))
    assert set(out) == {"SLAM / localization", "grasp planning"}
    assert all(k["session"] == "s1" for k in fake.calls)
    c = out["SLAM / localization"][0]
    assert c.name == "Cartographer" and c.domain == "github.com" and len(out["grasp planning"]) == 1


def test_verify_enforces_evidence(monkeypatch):
    fake = FakeAsync([("https://docs.ros.org/cartographer", "Cartographer ROS", "Cartographer Apache-2.0 ROS 2"),
                      ("https://news.example.com/x", "Cartographer review", "Cartographer is widely used")])
    monkeypatch.setattr(software, "async_client", lambda: fake)
    monkeypatch.setattr(tavily_client, "search", lambda q, tr, st, n=5: [])
    monkeypatch.setattr(llm, "call_json", lambda s, u, schema, m=0: schema(candidates=[
        {"candidate_index": 0, "decision": "keep", "reason": "ok", "license": "Apache-2.0", "cost_model": "free / open-source",
         "maintenance": "maintained", "maturity": "production", "integration": "ROS 2 package", "fit": "good", "rank": 1,
         "evidence": [0, 1]},
        {"candidate_index": 1, "decision": "keep", "reason": "no cites", "license": "?", "cost_model": "?",
         "maintenance": "unknown", "maturity": "unknown", "integration": "", "fit": "partial", "rank": 2, "evidence": [42]}]))
    mk = lambda n: SoftwareCandidate(requirement="SLAM", name=n, provider="p", url=f"https://{n}.io", domain=f"{n}.io",
                                     reason="r", found_by_provider="exa", found_by_query="q")
    res = software.verify({"SLAM": [mk("Cartographer"), mk("Ghost")]}, "farm robot", TelemRun(session_id="s1"))
    a, b = res["SLAM"]
    assert a.decision == "keep" and a.validation == "validated" and a.rank == 1
    assert b.decision == "eliminate" and "No evidence" in b.reason   # invalid citation -> eliminated
