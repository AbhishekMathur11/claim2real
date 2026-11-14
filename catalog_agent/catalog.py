"""Catalog reader: shortlisted Candidates -> CandidateProfiles with quoted, unit-normalized claims.

Flow
1. Telem fetch of every product URL (markdown, inline, batches of 5, same session).
2. Per URL: failed / empty / bot-wall page -> Tavily Extract fallback (extraction_engine="tavily").
3. LLM extracts claims ONLY for the checklist's fields (+ closely related ones), each with a
   verbatim quote, plus price, availability, contact and datasheet links.
4. Code checks every quote is on the fetched page (claims without one are dropped), converts
   values to canonical units, and computes meets / fails / unknown per requirement.

CLI (from catalog_agent/):  python catalog.py ../discovery_agent/cache/discovery.json [--out cache/catalog.json] [--limit N]
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

import config
import llm
import tavily_client
import units
from models import Candidate, CandidateProfile, Claim, RequirementsChecklist, SearchTrace
from telem_client import TelemRun

STAGE = "catalog"

# Fields worth extracting alongside a required one (e.g. to catch peak-vs-continuous torque).
RELATED_FIELDS = {
    "continuous_torque_nm": ["peak_torque_nm"],
    "peak_torque_nm": ["continuous_torque_nm"],
    "payload_kg": ["mass_kg"],
    "rated_speed_rpm": [],
}
_BOT_WALL = re.compile(r"captcha|access denied|verify you are (a )?human|enable javascript|just a moment|"
                       r"attention required|403 forbidden", re.I)


# ---------------------------------------------------------------- page fetching

def _usable(content: str | None) -> bool:
    if not content or len(content.strip()) < config.MIN_PAGE_CHARS:
        return False
    return not (len(content) < 3000 and _BOT_WALL.search(content))


def fetch_pages(urls: list[str], run: TelemRun) -> dict[str, tuple[str, str]]:
    """Return {url: (content, engine)}; engine is "telem", "tavily" or "" (unreadable)."""
    results = run.fetch(STAGE, urls, chunk=config.FETCH_BATCH, content_format="markdown",
                        inline_content=True, inline_max_chars=config.FETCH_MAX_CHARS)
    pages: dict[str, tuple[str, str]] = {}
    need_fallback = []
    for u in urls:
        r = results.get(u)
        if r is not None and _usable(r.content):
            pages[u] = (r.content or "", "telem")
        else:
            need_fallback.append(u)

    if need_fallback:
        tav_traces: list[list[SearchTrace]] = [[] for _ in need_fallback]
        with ThreadPoolExecutor(max_workers=4) as ex:
            outs = list(ex.map(lambda a: tavily_client.extract(a[0], a[1], STAGE), zip(need_fallback, tav_traces)))
        for u, (content, _), tr in zip(need_fallback, outs, tav_traces):
            run.traces.extend(tr)
            pages[u] = (content[: config.FETCH_MAX_CHARS], "tavily") if _usable(content) else ("", "")
    return pages


# ---------------------------------------------------------------- quote checking

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace(" ", " ").replace("⋅", "·")
    text = re.sub(r"[*_`|#>\[\]\\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_on_page(quote: str, page_norm: str) -> bool:
    """Exact (normalized) match, or a contiguous block covering >=85% of the quote."""
    q = _norm(quote)
    if len(q) < 4:
        return False
    if q in page_norm:
        return True
    m = difflib.SequenceMatcher(None, page_norm, q, autojunk=False).find_longest_match(0, len(page_norm), 0, len(q))
    return m.size >= 0.85 * len(q)


def value_in_quote(value: float | int | str, quote: str) -> bool:
    """For numeric claims the number must actually appear in the quote (blocks invented values)."""
    num = units.parse_number(value)
    if num is None or isinstance(value, str) and not re.search(r"\d", value):
        return True
    text = _norm(quote).replace(",", "")
    shown = f"{num:g}"
    return shown in text or shown.lstrip("0") in text


# ---------------------------------------------------------------- LLM extraction

class ExtractedClaim(BaseModel):
    field: str
    value: float | str
    unit: str | None = None
    quote: str


class Extraction(BaseModel):
    product_name: str | None = None
    vendor: str | None = None
    claims: list[ExtractedClaim] = []
    price_amount: float | None = None
    price_currency: str | None = None
    price_quote: str | None = None
    availability: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    datasheet_urls: list[str] = []


EXTRACT_SYSTEM = """You extract technical claims from ONE product web page for a robotics sourcing tool.
Use ONLY the page text provided. Never use outside knowledge. If a field is not on the page, omit it.
Rules:
- Only use the field names listed. Use each field at most once, for the product this page is about
  (if the page lists several variants, use the variant named in the page title/URL).
- value and unit exactly as written on the page (e.g. 900 and "g", or 25 and "kgf·cm"); do not convert.
- quote: a verbatim snippet of at most 25 words copied from the page that contains the value.
- Do not confuse peak/max torque with continuous/rated/nominal torque: "rated" or "nominal" = continuous.
- Categorical fields (unit null): value is the text on the page, e.g. "CAN, RS485".
- price: unit price for one item as listed, with currency code and a verbatim quote. Omit if not listed.
- availability: short stock / lead-time text as written (e.g. "In stock, ships in 3-5 days").
- contact_email / contact_phone only if shown on the page. datasheet_urls: links to datasheets/PDFs on the page."""


def _fields_for(c: RequirementsChecklist) -> dict[str, str | None]:
    names: list[str] = []
    for r in c.must_have + c.nice_to_have:
        names += [r.field] + RELATED_FIELDS.get(r.field, [])
    return {n: config.CANONICAL_FIELDS.get(n) for n in dict.fromkeys(names)}


def extract(cand: Candidate, page: str, c: RequirementsChecklist) -> Extraction:
    fields = "\n".join(f"- {n}: " + (f"numeric, canonical unit {u}" if u else "categorical")
                       for n, u in _fields_for(c).items())
    user = (f"Fields:\n{fields}\n\nProduct: {cand.name} ({cand.vendor})\nURL: {cand.url}\n\n"
            f"Page text:\n{page[: config.FETCH_MAX_CHARS]}")
    return llm.call_json(EXTRACT_SYSTEM, user, Extraction, max_tokens=1500)


# ---------------------------------------------------------------- build profile

def build_profile(cand: Candidate, page: str, engine: str, ex: Extraction | None,
                  c: RequirementsChecklist) -> CandidateProfile:
    if not page:
        return _profile(cand, [], c, engine or "telem", page_status="unreadable")
    if ex is None:
        return _profile(cand, [], c, engine, page_status="extraction_failed")

    page_norm = _norm(page)
    allowed = _fields_for(c)
    claims, dropped = [], 0
    seen_fields: set[str] = set()
    for e in ex.claims:
        if e.field not in allowed or not quote_on_page(e.quote, page_norm) or not value_in_quote(e.value, e.quote):
            dropped += 1
            continue
        if e.field in seen_fields:  # one valid claim per field (the first, for the page's main product)
            continue
        conv = units.to_canonical(e.field, e.value, e.unit)
        value, unit = conv if conv else (e.value, e.unit)
        claims.append(Claim(field=e.field, value=value, unit=unit, quote=" ".join(e.quote.split()[:25]),
                            source_url=cand.url))
        seen_fields.add(e.field)

    price_usd = price_quote = None
    if ex.price_amount is not None and ex.price_quote and quote_on_page(ex.price_quote, page_norm):
        price_usd, price_quote = units.to_usd(ex.price_amount, ex.price_currency), ex.price_quote
    contact = next((x for x in (ex.contact_email, ex.contact_phone) if x and _norm(x) in page_norm), None)
    datasheets = [u for u in ex.datasheet_urls if u.startswith("http") and u in page]

    p = _profile(cand, claims, c, engine, price_usd=price_usd, price_quote=price_quote,
                 availability=ex.availability, contact=contact, datasheet_urls=datasheets,
                 product_name=ex.product_name or cand.name, dropped_claims=dropped)
    return p


def _profile(cand: Candidate, claims: list[Claim], c: RequirementsChecklist, engine: str, **kw) -> CandidateProfile:
    fit = compute_fit(claims, c, kw.get("price_usd"))
    return CandidateProfile(candidate=cand, claims=claims, extraction_engine=engine or "telem",
                            requirement_fit=fit, **kw)


def compute_fit(claims: list[Claim], c: RequirementsChecklist, price_usd: float | None) -> dict[str, str]:
    """Per requirement: meets if any claim satisfies it, fails if claims exist and none do, else unknown.
    Also sets Claim.fit in place."""
    fit: dict[str, str] = {}
    for req in c.must_have + c.nice_to_have:
        mine = [cl for cl in claims if cl.field == req.field]
        for cl in mine:
            comparable = req.operator == "has" or cl.unit == req.unit or req.unit is None
            if not comparable:
                cl.fit = "unknown"
            elif units.check(req.operator, req.value, cl.value):
                cl.fit = "meets"
            else:  # a non-matching categorical value only fails when the page lists the full set
                exhaustive = req.operator != "has" or req.field in units.EXHAUSTIVE_CATEGORICAL
                cl.fit = "fails" if exhaustive else "unknown"
        verdicts = {cl.fit for cl in mine}
        fit[req.field] = "meets" if "meets" in verdicts else "fails" if verdicts == {"fails"} else "unknown"
    if c.budget_usd is not None:
        fit["budget_usd"] = "unknown" if price_usd is None else ("meets" if price_usd <= c.budget_usd else "fails")
    return fit


# ---------------------------------------------------------------- entry point

def read_catalog(candidates: list[Candidate], checklist: RequirementsChecklist, run: TelemRun) -> list[CandidateProfile]:
    pages = fetch_pages([c.url for c in candidates], run)

    def work(cand: Candidate) -> CandidateProfile:
        page, engine = pages.get(cand.url, ("", ""))
        ex = None
        if page:
            try:
                ex = extract(cand, page, checklist)
            except Exception as e:  # noqa: BLE001
                print(f"[catalog] extraction failed for {cand.url}: {str(e)[:200]}", file=sys.stderr)
        return build_profile(cand, page, engine, ex, checklist)

    with ThreadPoolExecutor(max_workers=config.CATALOG_WORKERS) as ex:
        return list(ex.map(work, candidates))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("discovery", type=Path, help="cache/discovery.json from the Discovery agent")
    ap.add_argument("--out", type=Path, default=Path("cache/catalog.json"))
    ap.add_argument("--limit", type=int, default=None, help="max candidates per component")
    args = ap.parse_args()

    data = json.loads(args.discovery.read_text())
    checklists = {c["component_type"]: RequirementsChecklist.model_validate(c) for c in data["checklists"]}
    run = TelemRun(session_id=data.get("telem_session_id"), goal=data.get("goal"),
                   traces=[SearchTrace.model_validate(t) for t in data.get("traces", [])])
    n_before = len(run.traces)

    profiles: dict[str, list[CandidateProfile]] = {}
    for comp, cands in data["candidates"].items():
        cands = [Candidate.model_validate(x) for x in cands][: args.limit]
        profiles[comp] = read_catalog(cands, checklists[comp], run)

    print(f"\nTelem session: {run.session_id}\n\nFetch / extract calls:")
    for t in run.traces[n_before:]:
        print(f"  {t.kind:<7} {t.provider:<16} {t.status[:24]:<24} {str(t.latency_ms or '-'):>6} ms  {t.query_or_url}")
    for comp, ps in profiles.items():
        print(f"\n== {comp}")
        for p in ps:
            price = f"${p.price_usd:g}" if p.price_usd is not None else "price ?"
            print(f"\n  {p.product_name or p.candidate.name} — {p.candidate.vendor}  [{p.extraction_engine}, "
                  f"{p.page_status}, {price}, {p.availability or 'availability ?'}]\n  {p.candidate.url}")
            print("    fit: " + ", ".join(f"{k}={v}" for k, v in p.requirement_fit.items()))
            for cl in p.claims:
                print(f"    - {cl.field} = {cl.value} {cl.unit or ''} [{cl.fit}]  \"{cl.quote}\"")
            if p.dropped_claims:
                print(f"    ({p.dropped_claims} claim(s) dropped: quote not found on page)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        **{k: data[k] for k in ("checklists", "goal")},
        "telem_session_id": run.session_id,
        "profiles": {k: [p.model_dump() for p in v] for k, v in profiles.items()},
        "traces": [t.model_dump() for t in run.traces],
    }, indent=2, default=str))
    print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    main()
