"""Discovery agent: RequirementsChecklist -> shortlisted Candidates via Telem search.

Flow
1. LLM query plan (5-8 queries tagged by angle), topped up deterministically so every
   angle is covered even if the LLM call fails.
2. Call A opens the Telem session: open-web queries batched, auto_routing="accuracy".
3. Call B (same session): recency queries with published_after.
4. Call C (same session): distributor queries scoped with include_domains.
5. Merge per-provider hits, dedupe by canonical URL, then by (domain, title).
6. LLM shortlists by index (cannot invent URLs); falls back to hit-count ranking.

Input is the Requirements agent's output ({"checklists": [...]} or a single checklist).
A system problem yields several components; all are searched in ONE Telem session.

CLI:  python -m agents.discovery fixtures/actuator_checklist.json [--component 0] [--out cache/discovery.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import tldextract
from pydantic import BaseModel

import config
import llm
from models import Candidate, RequirementsChecklist, load_checklists
from telem_client import TelemRun

STAGE = "discovery"
Angle = Literal["spec", "budget", "alternative", "recency", "distributor"]
ANGLES: tuple[Angle, ...] = ("spec", "budget", "alternative", "recency", "distributor")

_tld = tldextract.TLDExtract(suffix_list_urls=())  # bundled suffix list, no network


# ---------------------------------------------------------------- query plan

class PlannedQuery(BaseModel):
    query: str
    angle: Angle


class QueryPlan(BaseModel):
    queries: list[PlannedQuery]


def _fmt_req(r) -> str:
    unit = f" {r.unit}" if r.unit else ""
    return f"{r.field} {r.operator} {r.value}{unit}"


def build_goal(c: RequirementsChecklist) -> str:
    musts = "; ".join(_fmt_req(r) for r in c.must_have)
    parts = [
        f"Source a {c.component_type} for a robotics project.",
        f"Must-haves: {musts}." if musts else "",
        f"Budget about ${c.budget_usd:g} per unit." if c.budget_usd else "",
        f"Needs to ship to {c.ship_to} within {c.max_lead_time_days} days." if c.ship_to and c.max_lead_time_days else "",
        "Find real purchasable products with spec sheets from manufacturers and distributors.",
    ]
    goal = " ".join(p for p in parts if p)
    if c.problem_statement:
        goal = f"{c.problem_statement.strip()} {goal}"
    return goal[:1500]


def build_run_goal(checklists: list[RequirementsChecklist]) -> str:
    """Session goal (sent once). Single component -> detailed goal; system -> problem + parts."""
    if len(checklists) == 1:
        return build_goal(checklists[0])
    problem = (checklists[0].problem_statement or "").strip()
    parts = ", ".join(c.component_type for c in checklists)
    return (f"{problem} Source these components for the robotics system: {parts}. "
            "Find real purchasable products with spec sheets from manufacturers and distributors.")[:1500]


def _fallback_queries(c: RequirementsChecklist) -> list[PlannedQuery]:
    """Deterministic queries per angle, used to fill gaps in the LLM plan."""
    terms = c.search_terms or [c.component_type]
    main, alt = terms[0], (terms[1] if len(terms) > 1 else terms[0])
    key_specs = " ".join(
        f"{r.value} {r.unit}" if r.operator != "has" else str(r.value) for r in c.must_have[:3]
    )
    year = date.today().year
    return [
        PlannedQuery(angle="spec", query=f"{main} {key_specs}".strip()),
        PlannedQuery(angle="budget", query=f"{main} under ${c.budget_usd:g}" if c.budget_usd else f"affordable {main}"),
        PlannedQuery(angle="alternative", query=f"{alt} robot arm {key_specs}".strip()),
        PlannedQuery(angle="recency", query=f"new {main} release {year}"),
        PlannedQuery(angle="distributor", query=f"{main} {key_specs}".strip()),
    ]


PLAN_SYSTEM = """You plan web searches to find purchasable robotics components.
Write 5-8 short search-engine queries (3-10 words, no quotes or operators) covering distinct angles:
- spec: lead with the key numeric specs and interface
- budget: component category plus price ceiling
- alternative: different technologies/architectures that could meet the need (e.g. quasi-direct drive, harmonic drive, planetary)
- recency: new product releases/launches in this category (use the current year given, not past years)
- distributor: plain product query that will be run only on distributor sites (digikey, robotshop, aliexpress...)
Include at least one query per angle. Target product pages and datasheets, not tutorials."""


def plan_queries(c: RequirementsChecklist) -> list[PlannedQuery]:
    try:
        user = f"Today is {date.today().isoformat()}.\n{c.model_dump_json(exclude={'assumptions'})}"
        plan = llm.call_json(PLAN_SYSTEM, user, QueryPlan, max_tokens=800)
        planned = plan.queries[:8]
    except Exception as e:  # noqa: BLE001 - never let planning kill the run
        print(f"[discovery] query plan LLM failed, using fallback: {e}", file=sys.stderr)
        planned = []
    seen = {q.query.lower().strip() for q in planned}
    covered = {q.angle for q in planned}
    for fq in _fallback_queries(c):
        if fq.angle not in covered and fq.query.lower() not in seen:
            planned.append(fq)
    return planned


# ---------------------------------------------------------------- search + merge

@dataclass
class Hit:
    url: str
    title: str
    snippet: str
    domain: str
    providers: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    angles: list[str] = field(default_factory=list)

    @property
    def strength(self) -> int:
        return len(set(self.providers)) + len(set(self.queries))


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunsplit(("https", host, path, "", ""))


def registered_domain(url: str) -> str:
    ext = _tld(url)
    return ext.top_domain_under_public_suffix or ext.domain or urlsplit(url).netloc


def _snippet(r) -> str:
    text = r.summary or " ".join(r.excerpt or []) or ""
    return re.sub(r"\s+", " ", text)[: config.SNIPPET_CHARS]


def _title_key(domain: str, title: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return f"{domain}|{t[:60]}"


def run_searches(plan: list[PlannedQuery], run: TelemRun, component: str) -> dict[str, Hit]:
    angle_of = {q.query: q.angle for q in plan}
    open_web = [q.query for q in plan if q.angle in ("spec", "budget", "alternative")]
    recency = [q.query for q in plan if q.angle == "recency"]
    distrib = [q.query for q in plan if q.angle == "distributor"]
    since = date.today() - timedelta(days=config.DISCOVERY_RECENCY_DAYS)

    calls = [
        (open_web, dict(context=f"discover candidate {component} products")),
        (recency, dict(context=f"discover recently released {component} products", published_after=since)),
        (distrib, dict(context=f"find {component} products listed at distributors",
                       include_domains=config.DISTRIBUTOR_DOMAINS[:20])),
    ]
    hits: dict[str, Hit] = {}
    for queries, opts in calls:
        if not queries:
            continue
        resp = run.search(STAGE, queries, auto_routing="accuracy",
                          num_results=config.DISCOVERY_NUM_RESULTS, **opts)
        if resp is None:
            continue
        for prun in resp.by_provider:
            q = prun.query or queries[min(prun.batch_index, len(queries) - 1)]
            for r in prun.results:
                if not r.url.startswith("http"):
                    continue
                key = canonical_url(r.url)
                h = hits.get(key)
                if h is None:
                    h = hits[key] = Hit(url=r.url, title=r.title or "", snippet=_snippet(r),
                                        domain=registered_domain(r.url))
                elif len(_snippet(r)) > len(h.snippet):
                    h.snippet = _snippet(r)
                h.providers.append(prun.provider)
                h.queries.append(q)
                h.angles.append(angle_of.get(q, "?"))
    return hits


_CONTENT_DOMAINS = {"dev.to", "medium.com", "reddit.com", "youtube.com", "wikipedia.org", "quora.com",
                    "patsnap.com", "linkedin.com", "facebook.com", "x.com", "twitter.com", "github.com"}
_CONTENT_PATH = re.compile(r"/(blogs?|articles?|news|resources|learn|guides?|forum|wiki|tag|category)(/|$)", re.I)
_PRODUCT_PATH = re.compile(r"/(products?|shop|item|dp|store|p)/|\.html?$", re.I)


def page_kind_score(h: Hit) -> int:
    """Heuristic: +1 likely product page, -2 likely article/listing. Used to rank, not to filter."""
    path = urlsplit(h.url).path
    if h.domain in _CONTENT_DOMAINS or _CONTENT_PATH.search(path):
        return -2
    return 1 if _PRODUCT_PATH.search(path) else 0


def dedupe(hits: dict[str, Hit]) -> list[Hit]:
    """Second pass: same vendor domain + same normalized title = same product."""
    by_title: dict[str, Hit] = {}
    for h in hits.values():
        k = _title_key(h.domain, h.title)
        if k in by_title:
            keep = by_title[k]
            keep.providers += h.providers
            keep.queries += h.queries
            keep.angles += h.angles
        else:
            by_title[k] = h
    return sorted(by_title.values(), key=lambda h: (h.strength + 2 * page_kind_score(h)), reverse=True)


# ---------------------------------------------------------------- shortlist

class Pick(BaseModel):
    index: int
    name: str
    vendor: str
    reason: str


class Shortlist(BaseModel):
    picks: list[Pick]


SHORTLIST_SYSTEM = """You shortlist robotics component candidates from search results.
Use ONLY the titles, snippets and URLs given; do not add products from memory.
Pick up to {n} distinct products most likely to satisfy the requirements. Prefer manufacturer
product pages and distributor listings; skip listicles, blogs, forums, videos and news unless
nothing better exists for that product. One pick per product (avoid duplicates of the same model).
For each pick give: index (from the list), name (product/model name), vendor (company selling or
making it), reason (one sentence tied to the requirements, mention uncertainty if specs are not visible)."""


def _hits_prompt(c: RequirementsChecklist, pool: list[Hit]) -> str:
    lines = [f"Requirements: {c.model_dump_json(exclude={'assumptions', 'problem_statement'})}", "", "Results:"]
    for i, h in enumerate(pool):
        lines.append(f"[{i}] {h.title[:120]} | {h.url}\n    {h.snippet[:config.SHORTLIST_SNIPPET_CHARS]}")
    return "\n".join(lines)


def _to_candidate(h: Hit, name: str, vendor: str, reason: str, component: str) -> Candidate:
    providers = list(dict.fromkeys(h.providers))
    return Candidate(name=name, vendor=vendor, url=h.url, vendor_domain=h.domain,
                     found_by_provider=", ".join(providers), found_by_query=h.queries[0], reason=reason,
                     component_type=component)


def shortlist(c: RequirementsChecklist, hits: list[Hit], n: int) -> list[Candidate]:
    pool = hits[: config.DISCOVERY_MAX_POOL]
    if not pool:
        return []
    try:
        sl = llm.call_json(SHORTLIST_SYSTEM.format(n=n), _hits_prompt(c, pool), Shortlist, max_tokens=1200)
        out, used = [], set()
        for p in sl.picks:
            if 0 <= p.index < len(pool) and p.index not in used:
                used.add(p.index)
                out.append(_to_candidate(pool[p.index], p.name, p.vendor, p.reason, c.component_type))
        if out:
            return out[:n]
    except Exception as e:  # noqa: BLE001
        print(f"[discovery] shortlist LLM failed, using ranking fallback: {e}", file=sys.stderr)
    return [_to_candidate(h, h.title[:80] or h.domain, h.domain, "Top-ranked by search agreement (LLM shortlist unavailable).",
                          c.component_type)
            for h in pool[:n]]


# ---------------------------------------------------------------- entry point

def discover(checklist: RequirementsChecklist, run: TelemRun, n: int | None = None) -> list[Candidate]:
    """Find and shortlist candidates for one component. Opens the run's session if not open."""
    n = n or config.DISCOVERY_SHORTLIST_SIZE
    run.goal = run.goal or build_goal(checklist)
    plan = plan_queries(checklist)
    run.discovery_plans[checklist.component_type] = plan
    hits = dedupe(run_searches(plan, run, checklist.component_type))
    return shortlist(checklist, hits, n)


def discover_all(checklists: list[RequirementsChecklist], run: TelemRun,
                 n: int | None = None) -> dict[str, list[Candidate]]:
    """Discover every component of a bundle, sequentially, in one Telem session."""
    run.goal = run.goal or build_run_goal(checklists)
    return {c.component_type: discover(c, run, n) for c in checklists}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("checklist", type=Path, help="Requirements agent output JSON")
    ap.add_argument("--component", type=int, default=None, help="only this checklist index")
    ap.add_argument("--out", type=Path, default=Path("cache/discovery.json"))
    ap.add_argument("-n", type=int, default=None)
    args = ap.parse_args()

    checklists = load_checklists(args.checklist)
    if args.component is not None:
        checklists = [checklists[args.component]]
    run = TelemRun()
    results = discover_all(checklists, run, args.n)

    print(f"\nTelem session: {run.session_id}")
    for comp, plan in run.discovery_plans.items():
        print(f"\nQuery plan [{comp}]:")
        for q in plan:
            print(f"  [{q.angle:<11}] {q.query}")
    print("\nProvider runs:")
    for t in run.traces:
        print(f"  {t.provider:<14} {t.status:<10} {str(t.latency_ms or '-'):>6} ms  {t.results:>2} results  {t.query_or_url}")
    for comp, candidates in results.items():
        print(f"\nShortlist [{comp}] ({len(candidates)}):")
        for i, cand in enumerate(candidates, 1):
            print(f"  {i}. {cand.name} — {cand.vendor}\n     {cand.url}\n"
                  f"     found by {cand.found_by_provider} via \"{cand.found_by_query}\"\n     {cand.reason}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "checklists": [c.model_dump() for c in checklists],
        "telem_session_id": run.session_id,
        "goal": run.goal,
        "query_plans": {k: [q.model_dump() for q in v] for k, v in run.discovery_plans.items()},
        "candidates": {k: [c.model_dump() for c in v] for k, v in results.items()},
        "traces": [t.model_dump() for t in run.traces],
    }, indent=2, default=str))
    print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    main()
