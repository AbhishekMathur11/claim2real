"""Offline tests for the Catalog reader: Telem fetch, Tavily and the LLM are mocked."""
from pathlib import Path
from unittest.mock import MagicMock

from telem.models import FetchResponse, FetchResult

import llm
import tavily_client
import units
import catalog
from models import Candidate, load_checklists
from telem_client import TelemRun

CHECK = load_checklists(Path(__file__).parent.parent / "fixtures/actuator_checklist.json")[0]

PAGE = """# AK80-9 Robotic Actuator
Rated torque: 9 N.m | Peak torque: 18 N.m
Weight: 485 g. Communication: CAN bus, CAN FD.
Price: $429.00 — In stock, ships in 3-5 business days.
Contact sales@cubemars.com for bulk orders. """ + "Filler spec text. " * 40


def cand(url):
    return Candidate(name="AK80-9", vendor="CubeMars", url=url, vendor_domain="cubemars.com",
                     found_by_provider="exa", found_by_query="q", reason="r", component_type=CHECK.component_type)


def test_units():
    assert units.to_canonical("mass_kg", 485, "g") == (0.485, "kg")
    assert units.to_canonical("continuous_torque_nm", 90, "kgf·cm")[0] == 8.825985
    assert units.to_canonical("continuous_torque_nm", "9", "N.m") == (9.0, "N·m")
    assert units.to_canonical("mass_kg", 1, "furlongs") is None
    assert units.check("has", "CAN", "CAN bus, RS485") and not units.check("has", "CAN", "EtherCAT")
    assert units.to_usd(100, "EUR") == 108.0


def test_quote_checks():
    page = catalog._norm(PAGE)
    assert catalog.quote_on_page("Rated torque: 9 N.m", page)
    assert catalog.quote_on_page("**Rated torque:** 9 N.m", page)       # markdown noise tolerated
    assert not catalog.quote_on_page("Rated torque: 12 N.m continuous", page)
    assert catalog.value_in_quote(9, "Rated torque: 9 N.m")
    assert not catalog.value_in_quote(12, "Rated torque: 9 N.m")


def test_read_catalog_with_tavily_fallback(monkeypatch):
    good, bad = "https://cubemars.com/ak80-9", "https://blocked.example/x"
    client = MagicMock()
    client.fetch.return_value = FetchResponse(session_id="s1", interaction_id="i", status="succeeded", results=[
        FetchResult(url=good, status="succeeded", content=PAGE, provider="exa", batch_index=0),
        FetchResult(url=bad, status="failed", content=None, error={"m": "403"}, batch_index=1),
    ])
    monkeypatch.setattr(tavily_client, "extract", lambda u, tr, st: (PAGE, ""))

    def fake_llm(system, user, schema, max_tokens=0):
        return schema(product_name="AK80-9", vendor="CubeMars", claims=[
            {"field": "continuous_torque_nm", "value": 9, "unit": "N.m", "quote": "Rated torque: 9 N.m"},
            {"field": "peak_torque_nm", "value": 18, "unit": "N.m", "quote": "Peak torque: 18 N.m"},
            {"field": "mass_kg", "value": 485, "unit": "g", "quote": "Weight: 485 g."},
            {"field": "comm_interface", "value": "CAN bus, CAN FD", "unit": None, "quote": "Communication: CAN bus, CAN FD."},
            {"field": "continuous_torque_nm", "value": 12, "unit": "Nm", "quote": "12 Nm continuous"},  # invented
            {"field": "power_w", "value": 300, "unit": "W", "quote": "Rated torque: 9 N.m"},           # not requested
        ], price_amount=429, price_currency="USD", price_quote="Price: $429.00",
           availability="In stock, ships in 3-5 business days", contact_email="sales@cubemars.com",
           datasheet_urls=["https://not-on-page.com/ds.pdf"])
    monkeypatch.setattr(llm, "call_json", fake_llm)

    run = TelemRun(client=client, session_id="s1")
    profiles = catalog.read_catalog([cand(good), cand(bad)], CHECK, run)

    assert client.fetch.call_args.kwargs["session"] == "s1"
    p, fb = profiles
    assert p.extraction_engine == "telem" and fb.extraction_engine == "tavily"
    assert {c.field for c in p.claims} == {"continuous_torque_nm", "peak_torque_nm", "mass_kg", "comm_interface"}
    assert p.dropped_claims == 2
    assert p.requirement_fit == {"continuous_torque_nm": "fails", "mass_kg": "meets",
                                 "comm_interface": "meets", "feedback": "unknown", "budget_usd": "meets"}
    assert p.price_usd == 429.0 and p.contact == "sales@cubemars.com" and p.datasheet_urls == []
    assert [t.kind for t in run.traces].count("fetch") == 2


def test_unreadable_and_llm_failure(monkeypatch):
    client = MagicMock()
    client.fetch.return_value = FetchResponse(session_id="s1", interaction_id="i", status="succeeded", results=[
        FetchResult(url="https://a.com/1", status="succeeded", content=PAGE, batch_index=0),
        FetchResult(url="https://b.com/2", status="succeeded", content="Just a moment... enable javascript", batch_index=1),
    ])
    monkeypatch.setattr(tavily_client, "extract", lambda u, tr, st: ("", ""))
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("402")))
    ok, blocked = catalog.read_catalog([cand("https://a.com/1"), cand("https://b.com/2")], CHECK,
                                       TelemRun(client=client, session_id="s1"))
    assert ok.page_status == "extraction_failed" and blocked.page_status == "unreadable"
    assert ok.requirement_fit["continuous_torque_nm"] == "unknown"
