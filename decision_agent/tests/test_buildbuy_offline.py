import buildbuy
import llm

HW = {"name": "robot arm", "kind": "hardware", "kept": [{"name": "Dobot CR5", "score": 0.87}], "eliminated": []}
SW = {"name": "SLAM", "kind": "software", "kept": [], "eliminated": [{"name": "X", "reason": "stale"}]}


def test_llm_path(monkeypatch):
    monkeypatch.setattr(llm, "call_json", lambda s, u, schema, m=0: schema(
        decision="buy", confidence="high", headline="h", reasons=["a"], risks=["b"], next_step="c"))
    r = buildbuy.decide("p", HW)
    assert r.decision == "buy" and r.source == "llm" and r.kind == "hardware" and r.requirement == "robot arm"


def test_rules_fallback(monkeypatch):
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert buildbuy.decide("p", HW).decision == "buy"
    sw = buildbuy.decide("p", SW)
    assert sw.decision == "build" and sw.source == "rules"
