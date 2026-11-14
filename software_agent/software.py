"""Software agent: search and validate the SOFTWARE requirements of a spec (hardware has its own agents).

  discover  spec -> per software requirement, a shortlist of real solutions (open-source packages,
            SDKs, commercial products, cloud services) found with Telem search in the run's session.
  verify    shortlist -> per candidate, independent evidence (Telem multi-provider search + Tavily
            second opinion), then Claude judges license / cost / maintenance / maturity / integration /
            fit using ONLY that evidence and keeps or eliminates each candidate. Code enforces the
            evidence rules: a candidate with no cited independent evidence is eliminated.

CLI (from software_agent/):
  python software.py discover spec.json --session <telem session> --out cache/software_discovery.json [-n 5]
  python software.py verify cache/software_discovery.json --out cache/software_verified.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import tldextract
from pydantic import BaseModel

import config
import llm
import tavily_client
from models import SearchTrace, SoftwareAssessment, SoftwareCandidate, SoftwareSource
from telem_client import TelemRun, async_client

_tld = tldextract.TLDExtract(suffix_list_urls=())
QUERY_CHUNK = 8            # queries per batched Telem call
SHORTLIST_SIZE = 4         # candidates per software requirement
EVIDENCE_PER_CANDIDATE = 10
EVIDENCE_CHARS = 450
CONCURRENCY = 4


def registered_domain(url: str) -> str:
    ext = _tld(url)
    return ext.top_domain_under_public_suffix or ext.domain or urlsplit(url).netloc


def software_requirements(bundle: dict) -> list[str]:
    """Top-level `software` list, else the union of each checklist's paired software; de-duplicated."""
    items = list(bundle.get("software") or [])
    if not items:
        for c in bundle.get("checklists") or []:
            items += c.get("software") or []
    seen, out = set(), []
    for s in items:
        s = str(s).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def problem_of(bundle: dict) -> str:
    cl = bundle.get("checklists") or [{}]
    return str((cl[0] or {}).get("problem_statement") or bundle.get("problem") or "")


# ================================================================ discover

def queries_for(req: str) -> list[str]:
    return [f"{req} open source ROS 2 package",
            f"{req} software SDK for robots",
            f"{req} commercial software robotics"]


class Pick(BaseModel):
    index: int
    name: str
    provider: str
    kind: Literal["open-source", "commercial", "cloud service", "framework", "unknown"]
    reason: str


class Picks(BaseModel):
    picks: list[Pick]


SHORTLIST_SYSTEM = """You shortlist software that implements ONE robotics software requirement.
Use ONLY the numbered search results; never add products from memory.
Pick up to {n} distinct, concrete solutions (a named library, ROS package, SDK, framework, commercial
product or cloud service) whose result page is about that solution itself: official site, GitHub repo,
docs, or the vendor's product page. Skip listicles, tutorials, forum threads and news unless nothing
better exists. One pick per solution.
For each: index (from the list), name, provider (organisation or maintainer), kind, and reason (one
sentence on why it fits the requirement and the robot described)."""


def _collect(resp, queries: list[str], req_of: dict[str, str], hits: dict[str, dict]) -> None:
    if resp is None:
        return
    for prun in resp.by_provider:
        q = prun.query or queries[min(prun.batch_index, len(queries) - 1)]
        req = req_of.get(q)
        if not req:
            continue
        for r in prun.results:
            if not r.url.startswith("http"):
                continue
            key = r.url.split("#")[0].split("?")[0].rstrip("/")
            h = hits[req].setdefault(key, {"url": r.url, "title": r.title or "", "providers": [], "query": q,
                                           "snippet": re.sub(r"\s+", " ", r.summary or " ".join(r.excerpt or []))[:300]})
            if prun.provider not in h["providers"]:
                h["providers"].append(prun.provider)


async def _search_rest(run: TelemRun, chunks: list[list[str]], req_of, hits) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    async with async_client() as client:
        async def one(chunk):
            async with sem:
                resp = await run.asearch(client, "software_discovery", chunk, context="discover software solutions",
                                         auto_routing="accuracy", num_results=6)
            _collect(resp, chunk, req_of, hits)
        await asyncio.gather(*(one(c) for c in chunks))


def shortlist(req: str, problem: str, pool: list[dict], n: int) -> list[SoftwareCandidate]:
    if not pool:
        return []
    lines = [f"Requirement: {req}", f"Robot / problem: {problem[:400]}", "", "Results:"]
    lines += [f"[{i}] {h['title'][:110]} | {h['url']}\n    {h['snippet']}" for i, h in enumerate(pool)]
    picks: list[Pick] = []
    try:
        picks = llm.call_json(SHORTLIST_SYSTEM.format(n=n), "\n".join(lines), Picks, 1500).picks
    except Exception as e:  # noqa: BLE001
        print(f"[software] shortlist LLM failed for {req!r}: {str(e)[:150]}", file=sys.stderr)
    out, used = [], set()
    for p in picks:
        if 0 <= p.index < len(pool) and p.index not in used:
            used.add(p.index)
            h = pool[p.index]
            out.append(SoftwareCandidate(requirement=req, name=p.name, provider=p.provider, url=h["url"],
                                         domain=registered_domain(h["url"]), kind=p.kind, reason=p.reason,
                                         found_by_provider=", ".join(h["providers"]), found_by_query=h["query"]))
    if not out:  # LLM unavailable: top results by provider agreement
        for h in pool[:n]:
            out.append(SoftwareCandidate(requirement=req, name=h["title"][:80] or h["url"], provider=registered_domain(h["url"]),
                                         url=h["url"], domain=registered_domain(h["url"]), reason="Top result by search agreement.",
                                         found_by_provider=", ".join(h["providers"]), found_by_query=h["query"]))
    return out[:n]


def discover(bundle: dict, run: TelemRun, n: int = SHORTLIST_SIZE) -> dict[str, list[SoftwareCandidate]]:
    reqs = software_requirements(bundle)
    problem = problem_of(bundle)
    if not reqs:
        return {}
    run.goal = run.goal or f"Find software solutions for this robot: {problem}"[:1500]
    req_of = {q: r for r in reqs for q in queries_for(r)}
    queries = list(req_of)
    chunks = [queries[i:i + QUERY_CHUNK] for i in range(0, len(queries), QUERY_CHUNK)]
    hits: dict[str, dict[str, dict]] = {r: {} for r in reqs}
    first = chunks.pop(0)
    if not run.session_id:  # never open a session with parallel calls
        _collect(run.search("software_discovery", first, context="discover software solutions",
                            auto_routing="accuracy", num_results=6), first, req_of, hits)
    else:
        chunks.insert(0, first)
    if chunks:
        asyncio.run(_search_rest(run, chunks, req_of, hits))
    with ThreadPoolExecutor(CONCURRENCY) as ex:
        lists = ex.map(lambda r: shortlist(r, problem, sorted(hits[r].values(), key=lambda h: -len(h["providers"]))[:25], n),
                       reqs)
    return dict(zip(reqs, lists))


# ================================================================ verify

class Ev(BaseModel):
    url: str
    domain: str
    title: str
    text: str
    engines: list[str]


def candidate_queries(c: SoftwareCandidate) -> list[str]:
    return [f"{c.name} license pricing", f"{c.name} github releases maintained",
            f"{c.name} ROS 2 robot integration", f"{c.name} review limitations"]


async def gather(c: SoftwareCandidate, run: TelemRun, client, sem) -> list[Ev]:
    qs = candidate_queries(c)
    async with sem:
        resp, tav = await asyncio.gather(
            run.asearch(client, "software_verify", qs, context=f"validate software {c.name} for {c.requirement}",
                        auto_routing="accuracy", max_routing_providers=2, num_results=4),
            asyncio.to_thread(tavily_client.search, f"{c.name} {c.requirement}", run.traces, "software_verify", 4))
    items: dict[str, Ev] = {}

    def add(url, title, text, engine):
        if not url.startswith("http"):
            return
        key = url.split("#")[0].rstrip("/")
        if key in items:
            if engine not in items[key].engines:
                items[key].engines.append(engine)
            return
        items[key] = Ev(url=url, domain=registered_domain(url), title=title or "",
                        text=re.sub(r"\s+", " ", text or "")[:EVIDENCE_CHARS], engines=[engine])
    if resp is not None:
        for prun in resp.by_provider:
            for r in prun.results:
                add(r.url, r.title, r.summary or " ".join(r.excerpt or []), f"telem:{prun.provider}")
    for r in tav:
        add(r.get("url", ""), r.get("title", ""), r.get("content", ""), "tavily")
    name = c.name.lower()
    ranked = sorted(items.values(), key=lambda e: (name not in (e.title + " " + e.text).lower(), -len(e.engines)))
    return ranked[:EVIDENCE_PER_CANDIDATE]


class CandJudgement(BaseModel):
    candidate_index: int
    decision: Literal["keep", "eliminate"]
    reason: str
    license: str
    cost_model: str
    maintenance: Literal["active", "maintained", "stale", "unknown"]
    maturity: Literal["production", "research", "experimental", "unknown"]
    integration: str
    fit: Literal["good", "partial", "poor", "unknown"]
    rank: int
    evidence: list[int]


class ReqJudgement(BaseModel):
    candidates: list[CandJudgement]


JUDGE_SYSTEM = """You validate software options for ONE robotics software requirement, using ONLY the numbered
evidence listed under each candidate. Never use outside knowledge; say "unknown" when evidence is silent.
For every candidate return:
- license (e.g. "Apache-2.0", "BSD-3", "proprietary") and cost_model ("free / open-source", "paid license",
  "subscription", "free tier + paid", or "unknown")
- maintenance: active (releases/commits in the last ~12 months), maintained, stale (no activity for years), unknown
- maturity: production (used in products/industry), research, experimental, unknown
- integration: one short phrase on robot-stack integration found in evidence (e.g. "ROS 2 package"), or ""
- fit for the requirement and the robot described: good / partial / poor / unknown
- decision keep or eliminate, with a one-sentence reason citing the evidence. Eliminate when the evidence
  shows it does not do this job, is abandoned/stale, is not a real product, or nothing in the evidence is
  about it. Keep the strongest options.
- rank: 1 = best kept option (0 for eliminated)
- evidence: indices (within that candidate's list) that support your findings."""


def _judge_prompt(req: str, problem: str, cands: list[SoftwareCandidate], evs: list[list[Ev]]) -> str:
    lines = [f"Requirement: {req}", f"Robot / problem: {problem[:400]}", ""]
    for ci, (c, ev) in enumerate(zip(cands, evs)):
        lines.append(f"## Candidate {ci}: {c.name} — {c.provider} ({c.kind}) {c.url}")
        lines += [f"  [{i}] {e.domain} | {e.title[:100]}\n      {e.text}" for i, e in enumerate(ev)] or ["  (no evidence)"]
        lines.append("")
    return "\n".join(lines)


def _sources(ev: list[Ev], idxs: list[int]) -> list[SoftwareSource]:
    return [SoftwareSource(url=ev[i].url, domain=ev[i].domain, title=ev[i].title, engine="+".join(ev[i].engines))
            for i in dict.fromkeys(idxs) if 0 <= i < len(ev)]


def assess(req: str, problem: str, cands: list[SoftwareCandidate], evs: list[list[Ev]]) -> list[SoftwareAssessment]:
    judged: dict[int, CandJudgement] = {}
    try:
        out = llm.call_json(JUDGE_SYSTEM, _judge_prompt(req, problem, cands, evs), ReqJudgement, 4000)
        judged = {j.candidate_index: j for j in out.candidates}
    except Exception as e:  # noqa: BLE001
        print(f"[software] judge LLM failed for {req!r}: {str(e)[:150]}", file=sys.stderr)
    results = []
    for ci, (c, ev) in enumerate(zip(cands, evs)):
        j = judged.get(ci)
        if j is None:  # LLM unavailable: keep only if two independent sites name it
            sup = [i for i, e in enumerate(ev) if c.name.lower() in (e.title + " " + e.text).lower()]
            srcs = _sources(ev, sup)
            doms = {s.domain for s in srcs}
            keep = len(doms) >= 2
            results.append(SoftwareAssessment(
                candidate=c, decision="keep" if keep else "eliminate",
                reason=("Named by independent sources (rule-based check; LLM review unavailable)." if keep
                        else "Too little independent evidence (rule-based check; LLM review unavailable)."),
                validation="validated" if keep else "partially validated" if doms else "unvalidated",
                sources=srcs[:4], rank=0))
            continue
        srcs = _sources(ev, j.evidence)
        doms = {s.domain for s in srcs if s.domain != c.domain}
        validation = "validated" if len(doms) >= 2 else "partially validated" if srcs else "unvalidated"
        decision, reason = j.decision, j.reason
        if decision == "keep" and not srcs:
            decision, reason = "eliminate", "No evidence about this product was found in the searches."
        results.append(SoftwareAssessment(
            candidate=c, decision=decision, reason=reason, validation=validation, license=j.license or "unknown",
            cost_model=j.cost_model or "unknown", maintenance=j.maintenance, maturity=j.maturity,
            integration=j.integration, fit=j.fit, rank=j.rank if decision == "keep" else 0, sources=srcs[:4]))
    kept = sorted([r for r in results if r.decision == "keep"],
                  key=lambda r: (r.rank or 99, {"good": 0, "partial": 1, "unknown": 2, "poor": 3}[r.fit]))
    for i, r in enumerate(kept, 1):
        r.rank = i
    return kept + [r for r in results if r.decision == "eliminate"]


async def _gather_all(cands: list[SoftwareCandidate], run: TelemRun) -> list[list[Ev]]:
    sem = asyncio.Semaphore(CONCURRENCY)
    async with async_client() as client:
        return list(await asyncio.gather(*(gather(c, run, client, sem) for c in cands)))


def verify(shortlists: dict[str, list[SoftwareCandidate]], problem: str, run: TelemRun) -> dict[str, list[SoftwareAssessment]]:
    flat = [c for cs in shortlists.values() for c in cs]
    if not flat:
        return {r: [] for r in shortlists}
    if not run.session_id:
        run.search("software_verify", f"{flat[0].name}", context="open software verification session")
    evs = asyncio.run(_gather_all(flat, run))
    ev_of = {id(c): e for c, e in zip(flat, evs)}
    with ThreadPoolExecutor(CONCURRENCY) as ex:
        out = ex.map(lambda r: assess(r, problem, shortlists[r], [ev_of[id(c)] for c in shortlists[r]]),
                     list(shortlists))
    return dict(zip(shortlists, out))


# ================================================================ CLI

def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover")
    d.add_argument("spec", type=Path)
    d.add_argument("--out", type=Path, default=Path("cache/software_discovery.json"))
    d.add_argument("--session", default=None)
    d.add_argument("-n", type=int, default=SHORTLIST_SIZE)
    v = sub.add_parser("verify")
    v.add_argument("discovery", type=Path)
    v.add_argument("--out", type=Path, default=Path("cache/software_verified.json"))
    args = ap.parse_args()

    if args.cmd == "discover":
        bundle = json.loads(args.spec.read_text())
        run = TelemRun(session_id=args.session)
        found = discover(bundle, run, args.n)
        for req, cs in found.items():
            print(f"\n== {req}")
            for c in cs:
                print(f"  - {c.name} ({c.provider}, {c.kind}) {c.url}  [found by {c.found_by_provider}]")
        _save(args.out, {"telem_session_id": run.session_id, "problem": problem_of(bundle),
                         "requirements": list(found), "candidates": {k: [c.model_dump() for c in v] for k, v in found.items()},
                         "traces": [t.model_dump() for t in run.traces]})
    else:
        data = json.loads(args.discovery.read_text())
        run = TelemRun(session_id=data.get("telem_session_id"),
                       traces=[SearchTrace.model_validate(t) for t in data.get("traces", [])])
        shortlists = {k: [SoftwareCandidate.model_validate(c) for c in v] for k, v in data["candidates"].items()}
        res = verify(shortlists, data.get("problem", ""), run)
        for req, rows in res.items():
            print(f"\n== {req}")
            for r in rows:
                print(f"  [{r.decision:<9}] {r.candidate.name} · {r.license} · {r.maintenance} · fit {r.fit} · {r.validation}"
                      f"\n              {r.reason}")
        _save(args.out, {"telem_session_id": run.session_id, "problem": data.get("problem", ""),
                         "results": {k: [r.model_dump() for r in v] for k, v in res.items()},
                         "traces": [t.model_dump() for t in run.traces]})
    print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    main()
