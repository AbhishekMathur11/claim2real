"""Claim verifier: CandidateProfiles -> ranked VerifiedCandidates with per-claim verdicts.

Flow (per candidate, candidates in parallel, all in the run's existing Telem session)
1. Pick up to 4 claims: must-have claims first, then price, then availability.
2. One batched Telem search per candidate (AsyncTelem, auto_routing="accuracy",
   max_routing_providers=3): a datasheet query per claim, plus review, price/stock and
   vendor-reputation queries.
3. Tavily second opinion: one advanced search per must-have claim.
4. Evidence independence: drop the seller's and the vendor's own domains.
5. LLM judge per candidate using ONLY that evidence -> verdict per claim + vendor risk.
   Code then enforces the rules: "verified" needs >=2 independent domains (or one
   authoritative source plus another item); "contradicted" needs a cited independent item.
   Without the LLM, a rule-based matcher (value + model name in evidence) is used.
6. Vendor/product report: a second batched Telem search (seller history, real-world use) plus an RDAP
   lookup of the seller domain feed vendor-criteria ratings, spec-vs-independent values, manufacturer
   background, release year and deployment examples. report.py renders it to Markdown.
7. Score (scoring.py) and rank.

CLI (from verifier_agent/):  python verifier.py ../catalog_agent/cache/catalog.json [--out cache/verified.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import tldextract
from pydantic import BaseModel

import config
import domain_age
import llm
import report
import scoring
import tavily_client
from models import (CandidateProfile, Claim, ClaimVerdict, CriterionResult, DeploymentItem, Evidence,
                    ProductMaturity, RequirementsChecklist, SearchTrace, Source, VendorProfile, VerifiedCandidate)
from telem_client import TelemRun, async_client

STAGE = "verifier"
_tld = tldextract.TLDExtract(suffix_list_urls=())
_UNIT_SUFFIX = re.compile(r"_(nm|kg|v|w|rpm|mm_s|mm|n|a|hz|deg|c|h|tops|gb|usd)$")
_DATASHEET = re.compile(r"datasheet|data-sheet|spec(ification)?s?\b|manual|\.pdf($|\?)", re.I)


# ---------------------------------------------------------------- helpers

def registered_domain(url: str) -> str:
    ext = _tld(url)
    return ext.top_domain_under_public_suffix or ext.domain or ""


def label(field_name: str) -> str:
    """continuous_torque_nm -> 'continuous torque'."""
    return _UNIT_SUFFIX.sub("", field_name).replace("_", " ")


def model_token(profile: CandidateProfile) -> str:
    """Best model identifier, e.g. 'AK80-9' or 'RMD-X4-10'; falls back to the product name."""
    name = profile.product_name or profile.candidate.name
    toks = [t.strip("()[],.") for t in name.split()]
    coded = [t for t in toks if re.search(r"[A-Za-z]", t) and re.search(r"\d", t) and len(t) >= 3]
    return max(coded, key=len) if coded else " ".join(toks[:4])


def vendor_slug(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]", "", vendor.lower())


def brand_name(profile: CandidateProfile) -> str:
    """Manufacturer brand: first word of the product name when it isn't the model, e.g. 'DAMIAO'."""
    words = (profile.product_name or profile.candidate.name).split()
    first = words[0].strip("()[],.") if words else ""
    return "" if not first or first == model_token(profile) or re.search(r"\d", first) else first


def own_domains(profile: CandidateProfile, domains: set[str]) -> set[str]:
    """The seller's domain plus any domain that is the vendor's own (name appears in it)."""
    out = {profile.candidate.vendor_domain, registered_domain(profile.candidate.url)}
    slug = vendor_slug(profile.candidate.vendor)
    if len(slug) >= 4:
        out |= {d for d in domains if slug in d.replace("-", "").replace(".", "")}
    return {d for d in out if d}


def claims_to_check(p: CandidateProfile, c: RequirementsChecklist) -> list[Claim]:
    must = [r.field for r in c.must_have]
    picked = sorted((cl for cl in p.claims if cl.field in must), key=lambda cl: must.index(cl.field))
    picked = list({cl.field: cl for cl in picked}.values())  # one claim per field
    if p.price_usd is not None and p.price_quote:
        picked.append(Claim(field="price_usd", value=p.price_usd, unit="USD", quote=p.price_quote,
                            source_url=p.candidate.url))
    if p.availability:
        picked.append(Claim(field="availability", value=p.availability, unit=None, quote=p.availability,
                            source_url=p.candidate.url))
    return picked[: config.VERIFY_MAX_CLAIMS]


# ---------------------------------------------------------------- evidence gathering

@dataclass
class Item:
    url: str
    domain: str
    title: str
    text: str
    engines: list[str] = field(default_factory=list)
    query: str = ""
    purpose: Literal["claim", "vendor", "deployment"] = "claim"
    published: str | None = None  # ISO date from the provider's publish_date, if any
    self_reported: bool = False   # seller's own about/contact page: vendor facts only, never claim evidence

    @property
    def authoritative(self) -> bool:
        return self.domain in config.DISTRIBUTOR_DOMAINS or bool(_DATASHEET.search(self.url + " " + self.title))

    def source(self) -> Source:
        return Source(url=self.url, domain=self.domain, title=self.title[:140], published=self.published)


def build_queries(p: CandidateProfile, claims: list[Claim]) -> tuple[list[str], list[str]]:
    """Return (telem batch queries, tavily queries)."""
    vendor, model = p.candidate.vendor, model_token(p)
    telem, tav = [], []
    for cl in claims:
        if cl.field == "price_usd":
            telem.append(f"{vendor} {model} price")
        elif cl.field == "availability":
            telem.append(f"{vendor} {model} in stock lead time")
        else:
            what = f"{cl.value} interface" if isinstance(cl.value, str) else label(cl.field)
            telem.append(f"{vendor} {model} {what} datasheet")
            tav.append(f"{vendor} {model} {label(cl.field)} specifications")
    telem += [f"{vendor} {model} review", f"{vendor} {model} price stock", f"{vendor} reviews complaints"]
    return list(dict.fromkeys(telem)), list(dict.fromkeys(tav))


def build_background_queries(p: CandidateProfile) -> dict[str, Literal["vendor", "deployment"]]:
    """Queries about the vendor's history and the product's real-world use -> {query: purpose}."""
    vendor, model, brand = p.candidate.vendor, model_token(p), brand_name(p)
    product = f"{brand} {model}".strip()
    q: dict[str, Literal["vendor", "deployment"]] = {f"{vendor} company about founded": "vendor"}
    if brand and vendor_slug(brand) not in vendor_slug(vendor):
        q[f"{brand} company founded robotics motors"] = "vendor"
    q[f"{product} robot project build"] = "deployment"
    q[f"{product} github"] = "deployment"
    q[f"{product} forum user experience"] = "deployment"
    return q


def _date(v) -> str | None:
    return str(v)[:10] if v else None


def _merge(items: dict[str, Item], url: str, title: str, text: str, engine: str, query: str,
           purpose: str = "claim", published: str | None = None) -> None:
    if not url.startswith("http"):
        return
    key = url.split("#")[0].rstrip("/")
    it = items.get(key)
    if it is None:
        items[key] = Item(url=url, domain=registered_domain(url), title=title or "",
                          text=re.sub(r"\s+", " ", text or "")[: config.EVIDENCE_CHARS], engines=[engine], query=query,
                          purpose=purpose, published=published)
    else:
        if engine not in it.engines:
            it.engines.append(engine)
        it.published = it.published or published


def _add_response(items: dict[str, Item], resp, queries: list[str], purpose_of: dict[str, str]) -> None:
    if resp is None:
        return
    for prun in resp.by_provider:
        q = prun.query or queries[min(prun.batch_index, len(queries) - 1)]
        for r in prun.results:
            text = r.summary or " ".join(r.excerpt or [])
            _merge(items, r.url, r.title, text, f"telem:{prun.provider}", q, purpose_of.get(q, "claim"),
                   _date(r.publish_date))


async def _lookup_age(domain: str) -> domain_age.DomainAge | None:
    if not config.VERIFY_DOMAIN_AGE:
        return None
    return await asyncio.to_thread(domain_age.lookup, domain)


async def gather_evidence(p: CandidateProfile, claims: list[Claim], run: TelemRun, client,
                          sem: asyncio.Semaphore) -> tuple[list[Item], domain_age.DomainAge | None]:
    """Two batched Telem searches (claims; vendor background + deployment), Tavily, and RDAP, in parallel."""
    telem_q, tav_q = build_queries(p, claims)
    bg = build_background_queries(p)
    bg_q = list(bg)
    opts = dict(auto_routing="accuracy", max_routing_providers=config.VERIFY_MAX_ROUTING_PROVIDERS,
                num_results=config.VERIFY_NUM_RESULTS)
    async with sem:
        claim_task = run.asearch(client, STAGE, telem_q, context=f"verify vendor claims for {model_token(p)}", **opts)
        bg_task = run.asearch(client, STAGE, bg_q,
                              context=f"vendor history and real-world deployments of {model_token(p)}", **opts)
        tav_tasks = [asyncio.to_thread(tavily_client.search, q, run.traces, STAGE, 5) for q in tav_q]
        resp, bg_resp, age, *tav_rows = await asyncio.gather(claim_task, bg_task,
                                                             _lookup_age(p.candidate.vendor_domain), *tav_tasks)

    items: dict[str, Item] = {}
    _add_response(items, resp, telem_q, {})
    _add_response(items, bg_resp, bg_q, bg)
    for q, rows in zip(tav_q, tav_rows):
        for r in rows:
            _merge(items, r.get("url", ""), r.get("title", ""), r.get("content", ""), "tavily", q,
                   published=_date(r.get("published_date")))
    return list(items.values()), age


def select_evidence(p: CandidateProfile, items: list[Item]) -> tuple[list[Item], set[str]]:
    """Drop own-domain items. Reserve slots for vendor-background and deployment items, then fill
    with claim evidence, most relevant (mentions the model, authoritative) first."""
    own = own_domains(p, {i.domain for i in items})
    model = model_token(p).lower()
    names = [n for n in (vendor_slug(p.candidate.vendor), vendor_slug(brand_name(p))) if len(n) >= 3]
    indep = [i for i in items if i.domain not in own]
    indep.sort(key=lambda i: (model not in (i.title + i.text).lower(), not i.authoritative, -len(i.engines)))
    slots = config.VERIFY_BACKGROUND_SLOTS
    vendor = sorted((i for i in indep if i.purpose == "vendor"),
                    key=lambda i: not any(n in vendor_slug(i.title + i.text) for n in names))[:slots]
    deploy = [i for i in indep if i.purpose == "deployment"][:slots]
    reserved = vendor + deploy
    rest = [i for i in indep if i not in reserved][: max(0, config.VERIFY_MAX_EVIDENCE - len(reserved))]
    # The seller's own about/contact pages: shown to the judge, labelled self-reported, for business type
    # and contact facts only (enforce() and the risk checks ignore them).
    self_rep = [i for i in items if i.domain in own and i.purpose == "vendor"][: config.VERIFY_SELF_REPORTED]
    for i in self_rep:
        i.self_reported = True
    return rest + reserved + self_rep, own


# ---------------------------------------------------------------- judging

class ClaimJudgement(BaseModel):
    claim_index: int
    verdict: Literal["verified", "contradicted", "unverified"]
    supporting: list[int] = []
    contradicting: list[int] = []
    note: str = ""
    independent_value: str = ""  # what independent evidence states, e.g. "9 N·m rated, 27 N·m peak"


VENDOR_CRITERIA = (
    "Time in market",
    "Company footprint",
    "Business type & sales channel",
    "Customer reviews & complaints",
    "Spec accuracy",
    "Price consistency",
    "Contact & transparency",
)
CRITERIA_HELP = {
    "Time in market": "how long the seller has operated: founding year in evidence, the registry facts, earliest mentions",
    "Company footprint": "independent presence: distributors, press, wikis, marketplaces, social profiles",
    "Business type & sales channel": "manufacturer, authorized distributor, reseller or marketplace seller; is the channel known",
    "Customer reviews & complaints": "reviews, ratings, complaint or fraud reports about the seller",
    "Spec accuracy": "do the seller's stated specs match independent sources (use the claim verdicts)",
    "Price consistency": "is the seller's price in line with other sellers of the same model",
    "Contact & transparency": "company name, address and contact details stated and consistent",
}
DEPLOYMENT_KINDS = Literal["project/build", "research paper", "product integration", "user review",
                           "forum discussion", "open-source code"]


class CriterionJudgement(BaseModel):
    criterion: Literal[VENDOR_CRITERIA]  # type: ignore[valid-type]
    rating: Literal["positive", "neutral", "concern", "unknown"]
    detail: str
    evidence: list[int] = []


class DeploymentJudgement(BaseModel):
    kind: DEPLOYMENT_KINDS
    summary: str
    evidence: int


class Judgement(BaseModel):
    claims: list[ClaimJudgement]
    vendor_risk: Literal["low", "medium", "high"]
    vendor_risk_reason: str
    business_type: Literal["manufacturer", "authorized distributor", "reseller", "marketplace seller",
                           "unknown"] = "unknown"
    founded_year: int = 0               # 0 = not stated (sentinels keep the output schema simple)
    founded_evidence: list[int] = []
    manufacturer_note: str = ""         # "<company>, founded <year>: <independent presence>", or ""
    manufacturer_evidence: list[int] = []
    criteria: list[CriterionJudgement] = []
    release_year: int = 0
    release_evidence: list[int] = []
    deployment_level: Literal["widely used", "some real-world use", "limited", "no evidence"] = "no evidence"
    deployment: list[DeploymentJudgement] = []
    technical_summary: str = ""
    commercial_summary: str = ""
    recommendation: str = ""


JUDGE_SYSTEM = """You audit a robotics vendor and its product using ONLY the numbered evidence and the registry
facts given. All evidence is from sources independent of the seller. Never use outside knowledge; when the
evidence does not say, answer unknown / null. Cite evidence by index.

1. Claims. For each claim decide:
- verified: evidence about THIS product/model states the same value (allow rounding/unit differences).
- contradicted: evidence about THIS product/model gives a materially different value (>10% for numbers),
  or shows e.g. that the stated figure is peak rather than continuous, or a different interface.
- unverified: no evidence clearly about this exact model states the value.
List evidence indices in supporting / contradicting (only items that mention the value for this model).
independent_value: what the independent evidence states for this spec (short, with units), or null.
note: one short sentence explaining the verdict, citing what the evidence says.

2. Vendor (the SELLER named below; the manufacturer brand may differ).
business_type and founded_year (only if an evidence item states it; cite founded_evidence).
Items marked [SELLER'S OWN SITE] are self-reported: use them only for business_type, contact details and
founded_year (say "self-reported" in the detail), never as support for a claim or as independent footprint.
Search results may include similarly named but unrelated companies; ignore any item not clearly about this seller.
manufacturer_note: if the brand differs from the seller, one sentence "<full company name>, founded <year if
stated>: <independent presence, e.g. exhibitions, distributors, open-source SDKs>". Put the evidence
indices in manufacturer_evidence, not in the sentence.
Use 0 for unknown years and "" for unknown text.
criteria: rate EVERY criterion listed in the user message as positive / neutral / concern / unknown, with a
one-sentence detail that states the concrete finding (numbers, dates, names) and the evidence indices.
vendor_risk (low/medium/high): complaints, scam/fraud reports, missing company footprint, a very young
domain, inconsistent contact details or prices. Phrase as risk signals; never call a vendor a scam.
Default to low when evidence shows an established company and nothing negative.

3. Product maturity. release_year: first release/launch year of this model if evidence states it.
deployment: up to 6 concrete examples of real-world use (builds, papers, products, user reviews, forum
threads, code repos) about THIS model, each with a one-sentence summary and one evidence index. Use "research
paper" only for academic papers or preprints; a catalogue, blog post or store listing is not one. A plain
retail listing is not deployment evidence.
deployment_level: widely used (many independent users/projects) / some real-world use / limited / no evidence.

4. Summaries (2-3 sentences each, concrete): technical_summary (specs as stated vs found, fit concerns),
commercial_summary (seller history, channel, price, availability, reputation), recommendation (what a
buyer should do next, e.g. ask for a datasheet, buy from another channel)."""


def _judge_prompt(p: CandidateProfile, claims: list[Claim], items: list[Item],
                  age: domain_age.DomainAge | None = None, earliest: Item | None = None) -> str:
    brand = brand_name(p)
    lines = [f"Product: {p.product_name or p.candidate.name} | seller: {p.candidate.vendor} | "
             f"manufacturer brand: {brand or 'unknown'} | model: {model_token(p)} | seller site: "
             f"{p.candidate.vendor_domain}",
             f"Seller page price: {p.price_quote or 'not stated'} | availability: {p.availability or 'not stated'} | "
             f"contact: {p.contact or 'not stated'}", "", "Registry facts (reliable):"]
    if age and age.registered:
        lines.append(f"- seller domain {age.domain} registered {age.registered} ({age.years} years ago), "
                     f"registrar {age.registrar or 'unknown'}")
    else:
        lines.append(f"- seller domain {p.candidate.vendor_domain}: registration date unknown")
    if earliest:
        lines.append(f"- earliest dated independent page naming the model: {earliest.published} ({earliest.domain})")
    lines += ["", "Claims:"]
    for i, cl in enumerate(claims):
        lines.append(f"[{i}] {cl.field} = {cl.value} {cl.unit or ''} (vendor page: \"{cl.quote}\")")
    lines += ["", "Vendor criteria to rate:"]
    lines += [f"- {c}: {CRITERIA_HELP[c]}" for c in VENDOR_CRITERIA]
    lines += ["", "Evidence:"]
    for i, it in enumerate(items):
        pub = f" | published {it.published}" if it.published else ""
        tag = " [SELLER'S OWN SITE]" if it.self_reported else ""
        lines.append(f"[{i}]{tag} {it.domain} | {it.title[:100]}{pub}\n    {it.text}")
    return "\n".join(lines)


def _states_same_number(claim: Claim, independent_value: str | None) -> bool:
    """True when a numeric claim's value is the first number in the independent value ("40 N·m rated; ...")."""
    if not isinstance(claim.value, (int, float)) or not independent_value:
        return False
    m = re.search(r"\d+(?:\.\d+)?", independent_value)
    return bool(m) and abs(float(m.group()) - float(claim.value)) <= 0.05 * max(abs(float(claim.value)), 1e-9)


def passes_verified_rule(sup: list[Item]) -> bool:
    domains = {i.domain for i in sup}
    return len(domains) >= 2 or (any(i.authoritative for i in sup) and len(sup) >= 2)


def _evidence(items: list[Item], idxs: list[int], notes: str) -> list[Evidence]:
    return [Evidence(url=items[i].url, domain=items[i].domain, note=notes or items[i].title[:120],
                     engine="+".join(items[i].engines)) for i in idxs[:2]]


def enforce(claim: Claim, j: ClaimJudgement | None, items: list[Item]) -> ClaimVerdict:
    """Apply the evidence rules to the LLM's verdict; downgrade to unverified when they fail."""
    if j is None:
        return ClaimVerdict(claim=claim, verdict="unverified", evidence=[])
    sup = [i for i in dict.fromkeys(j.supporting) if 0 <= i < len(items) and not items[i].self_reported]
    con = [i for i in dict.fromkeys(j.contradicting) if 0 <= i < len(items) and not items[i].self_reported]
    iv = j.independent_value or None
    if j.verdict == "contradicted" and con and _states_same_number(claim, iv):
        # The judge's own independent_value repeats the claimed number: not a contradiction. Re-check the
        # cited items under the verified rule instead.
        cited = list(dict.fromkeys(sup + con))
        ok = passes_verified_rule([items[i] for i in cited])
        return ClaimVerdict(claim=claim, verdict="verified" if ok else "unverified",
                            evidence=_evidence(items, cited, j.note), independent_value=iv)
    if j.verdict == "contradicted" and con:
        return ClaimVerdict(claim=claim, verdict="contradicted", evidence=_evidence(items, con, j.note),
                            independent_value=iv)
    if j.verdict == "verified" and passes_verified_rule([items[i] for i in sup]):
        return ClaimVerdict(claim=claim, verdict="verified", evidence=_evidence(items, sup, j.note),
                            independent_value=iv)
    return ClaimVerdict(claim=claim, verdict="unverified", evidence=_evidence(items, sup, j.note),
                        independent_value=iv if sup else None)


def rule_based_judgement(p: CandidateProfile, claims: list[Claim], items: list[Item]) -> Judgement:
    """No-LLM fallback: an item supports a claim if it names the model and states the value."""
    model = model_token(p).lower()
    out = []
    for ci, cl in enumerate(claims):
        if isinstance(cl.value, (int, float)):
            pat = re.compile(rf"(?<![\d.]){re.escape(f'{cl.value:g}')}(?![\d])")
        else:
            pat = re.compile(re.escape(str(cl.value).split(",")[0].strip().lower()), re.I)
        sup = [i for i, it in enumerate(items)
               if model in (it.title + " " + it.text).lower() and pat.search(it.title + " " + it.text)]
        verdict = "verified" if passes_verified_rule([items[i] for i in sup]) else "unverified"
        out.append(ClaimJudgement(claim_index=ci, verdict=verdict, supporting=sup,
                                  note="Rule-based: value and model found in independent sources." if sup else ""))
    return Judgement(claims=out, vendor_risk="low", vendor_risk_reason="")


def code_risk_signals(p: CandidateProfile, items: list[Item], own: set[str],
                      age: domain_age.DomainAge | None = None) -> list[str]:
    signals = []
    if age and age.years_exact is not None and age.years_exact < config.VERIFY_YOUNG_DOMAIN_YEARS:
        signals.append(f"seller domain {age.domain} was registered only {age.years} years ago ({age.registered})")
    email = re.search(r"[\w.+-]+@([\w-]+\.[\w.-]+)", p.contact or "")
    if email:
        dom = registered_domain("https://" + email.group(1))
        slug = vendor_slug(p.candidate.vendor)
        if dom in config.FREE_MAIL_DOMAINS:
            signals.append(f"contact uses a free email domain ({dom})")
        elif dom not in own and not (len(slug) >= 4 and slug in dom.replace("-", "").replace(".", "")):
            signals.append(f"contact email domain ({dom}) differs from the vendor's site")
    names = [n for n in (vendor_slug(p.candidate.vendor), vendor_slug(model_token(p))) if len(n) >= 3]
    if names and not any(n in vendor_slug(i.title + i.text) for i in items for n in names):
        signals.append("little independent footprint found for this vendor or model")
    return signals


_LEVEL = {"low": 0, "medium": 1, "high": 2}


def _already_said(signal: str, text: str) -> bool:
    """Skip a code signal the LLM already stated (e.g. both mention the young domain)."""
    t = text.lower()
    return ("registered only" in signal and "registered" in t) or ("footprint" in signal and "footprint" in t)


def combine_risk(llm_level: str, llm_reason: str, signals: list[str]) -> tuple[str, str]:
    code_level = "high" if len(signals) >= 2 else "medium" if signals else "low"
    level = max(llm_level, code_level, key=_LEVEL.get)
    extra = [s for s in signals if not _already_said(s, llm_reason)]
    reason = "; ".join([r.rstrip(". ") for r in [llm_reason] + extra if r]) or "No risk signals found."
    return level, reason


def earliest_mention(p: CandidateProfile, items: list[Item]) -> Item | None:
    """Earliest dated independent item that names the model."""
    model = model_token(p).lower()
    dated = [i for i in items if i.published and re.match(r"\d{4}-\d{2}-\d{2}", i.published)
             and model in (i.title + " " + i.text).lower()]
    return min(dated, key=lambda i: i.published, default=None)


def _sources(items: list[Item], idxs: list[int] | int) -> list[Source]:
    idxs = [idxs] if isinstance(idxs, int) else idxs
    return [items[i].source() for i in dict.fromkeys(idxs) if 0 <= i < len(items)]


def _years_since(iso: str | None = None, year: int | None = None) -> float | None:
    today = date.today()
    if year:  # release month unknown: count whole calendar years
        return float(max(0, today.year - year))
    if iso:
        return round((today - date.fromisoformat(iso[:10])).days / 365.25, 1)
    return None


def spec_accuracy(verdicts: list[ClaimVerdict]) -> tuple[str, str] | None:
    """Code-derived Spec accuracy rating from the enforced claim verdicts (spec claims only)."""
    specs = [v for v in verdicts if v.claim.field not in ("price_usd", "availability")]
    if not specs:
        return None
    bad = [v.claim.field for v in specs if v.verdict == "contradicted"]
    ok = [v.claim.field for v in specs if v.verdict == "verified"]
    if bad:
        return "concern", f"{len(bad)} of {len(specs)} checked specs contradicted by independent sources ({', '.join(bad)})."
    if ok:
        return ("positive" if len(ok) == len(specs) else "neutral",
                f"{len(ok)} of {len(specs)} checked specs confirmed by independent sources; none contradicted.")
    return "unknown", "No checked spec could be confirmed or refuted from independent sources."


def build_vendor_profile(p: CandidateProfile, j: Judgement, items: list[Item], age: domain_age.DomainAge | None,
                         signals: list[str], llm_used: bool,
                         verdicts: list[ClaimVerdict] | None = None) -> VendorProfile:
    rated = {c.criterion: c for c in j.criteria} if llm_used else {}
    criteria = []
    for name in VENDOR_CRITERIA:
        cj = rated.get(name)
        res = CriterionResult(criterion=name, rating=cj.rating if cj else "unknown",
                              detail=cj.detail if cj else "Not assessed (LLM review unavailable).",
                              sources=_sources(items, cj.evidence) if cj else [])
        if name == "Time in market" and age and age.registered:
            res.detail += f" Seller domain registered {age.registered} ({age.years} years, RDAP)."
            res.sources.append(Source(url=age.source_url, domain="rdap.org", title=f"RDAP record for {age.domain}"))
            if age.years_exact < config.VERIFY_YOUNG_DOMAIN_YEARS:
                res.rating = "concern"
        if name == "Spec accuracy" and (sa := spec_accuracy(verdicts or [])):
            res.rating, res.detail = sa[0], sa[1] + (f" {cj.detail}" if cj else "")
        if name == "Contact & transparency" and any("contact" in s for s in signals):
            res.rating = "concern"
            res.detail += " Code check: " + "; ".join(s for s in signals if "contact" in s) + "."
        criteria.append(res)
    return VendorProfile(
        business_type=j.business_type if llm_used else "unknown",
        founded_year=(j.founded_year or None) if llm_used and j.founded_evidence else None,
        founded_sources=_sources(items, j.founded_evidence) if llm_used else [],
        manufacturer_note=j.manufacturer_note if llm_used and j.manufacturer_evidence else "",
        manufacturer_sources=_sources(items, j.manufacturer_evidence) if llm_used else [],
        domain=p.candidate.vendor_domain,
        domain_registered=str(age.registered) if age and age.registered else None,
        domain_age_years=age.years if age else None,
        domain_registrar=age.registrar if age else None,
        domain_source_url=age.source_url if age else None,
        criteria=criteria,
    )


def build_maturity(j: Judgement, items: list[Item], earliest: Item | None, llm_used: bool) -> ProductMaturity:
    release_year = (j.release_year or None) if llm_used and j.release_evidence else None
    deployment = [DeploymentItem(kind=d.kind, summary=d.summary, source=s[0])
                  for d in (j.deployment if llm_used else []) if (s := _sources(items, d.evidence))]
    return ProductMaturity(
        release_year=release_year,
        release_sources=_sources(items, j.release_evidence) if release_year else [],
        earliest_independent_mention=earliest.published if earliest else None,
        earliest_mention_source=earliest.source() if earliest else None,
        years_on_market=_years_since(year=release_year) if release_year else
        _years_since(iso=earliest.published) if earliest else None,
        deployment_level=j.deployment_level if llm_used and deployment else "no evidence",
        deployment=deployment,
    )


async def verify_one(p: CandidateProfile, c: RequirementsChecklist, run: TelemRun, client,
                     sem: asyncio.Semaphore) -> VerifiedCandidate:
    claims = claims_to_check(p, c)
    items_all, age = await gather_evidence(p, claims, run, client, sem)
    items, own = select_evidence(p, items_all)
    earliest = earliest_mention(p, [i for i in items_all if i.domain not in own])

    judgement: Judgement | None = None
    if claims or items:
        try:
            judgement = await asyncio.to_thread(llm.call_json, JUDGE_SYSTEM,
                                                _judge_prompt(p, claims, items, age, earliest), Judgement, 4000)
        except Exception as e:  # noqa: BLE001
            print(f"[verifier] judge LLM failed for {p.candidate.url}: {str(e)[:160]}", file=sys.stderr)
    llm_used = judgement is not None
    judgement = judgement or rule_based_judgement(p, claims, items)

    by_idx = {j.claim_index: j for j in judgement.claims}
    verdicts = [enforce(cl, by_idx.get(i), items) for i, cl in enumerate(claims)]
    signals = code_risk_signals(p, [i for i in items if not i.self_reported], own, age)
    level, reason = combine_risk(judgement.vendor_risk if llm_used else "low",
                                 judgement.vendor_risk_reason if llm_used else
                                 "LLM risk review unavailable; based on code checks only", signals)
    s, meets = scoring.score(p, c, verdicts, level)
    return VerifiedCandidate(
        profile=p, verdicts=verdicts, vendor_risk=level, vendor_risk_reason=reason, score=s,
        meets_requirements=meets, score_breakdown=scoring.breakdown(p, c, verdicts, level),
        vendor_profile=build_vendor_profile(p, judgement, items, age, signals, llm_used, verdicts),
        maturity=build_maturity(judgement, items, earliest, llm_used),
        technical_summary=judgement.technical_summary if llm_used else "",
        commercial_summary=judgement.commercial_summary if llm_used else "",
        recommendation=judgement.recommendation if llm_used else "",
        evidence_count=sum(not i.self_reported for i in items),
    )


async def _verify_all(profiles: list[CandidateProfile], c: RequirementsChecklist, run: TelemRun) -> list[VerifiedCandidate]:
    sem = asyncio.Semaphore(config.VERIFY_CONCURRENCY)
    async with async_client() as client:
        return list(await asyncio.gather(*(verify_one(p, c, run, client, sem) for p in profiles)))


def verify(profiles: list[CandidateProfile], checklist: RequirementsChecklist, run: TelemRun) -> list[VerifiedCandidate]:
    """Verify and rank one component's candidates. Needs the run's Telem session to be open."""
    if not run.session_id:  # never open a session with parallel calls
        run.search(STAGE, f"{checklist.component_type} vendors", context="open verification session")
    return scoring.rank(asyncio.run(_verify_all(profiles, checklist, run)))


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("catalog", type=Path, help="cache/catalog.json from the Catalog reader")
    ap.add_argument("--out", type=Path, default=Path("cache/verified.json"))
    ap.add_argument("--limit", type=int, default=None, help="max candidates per component")
    ap.add_argument("--report", type=Path, default=None,
                    help="Markdown report path (default: <out> with _report.md)")
    args = ap.parse_args()

    data = json.loads(args.catalog.read_text())
    checklists = {c["component_type"]: RequirementsChecklist.model_validate(c) for c in data["checklists"]}
    run = TelemRun(session_id=data.get("telem_session_id"), goal=data.get("goal"),
                   traces=[SearchTrace.model_validate(t) for t in data.get("traces", [])])
    n_before = len(run.traces)

    ranked: dict[str, list[VerifiedCandidate]] = {}
    for comp, ps in data["profiles"].items():
        profiles = [CandidateProfile.model_validate(x) for x in ps][: args.limit]
        ranked[comp] = verify(profiles, checklists[comp], run)

    new = run.traces[n_before:]
    tel = [t for t in new if t.kind == "search"]
    tav = [t for t in new if t.kind == "tavily"]
    print(f"\nTelem session: {run.session_id}")
    print(f"Verifier calls: {len(tel)} Telem provider runs across {len({t.provider for t in tel})} providers, "
          f"{len(tav)} Tavily searches")
    for comp, vcs in ranked.items():
        print(f"\n== {comp}")
        for i, v in enumerate(vcs, 1):
            p = v.profile
            flag = "" if v.meets_requirements else "  [does not meet requirements]"
            print(f"\n {i}. {p.product_name or p.candidate.name} — {p.candidate.vendor}   score {v.score:.2f}"
                  f"   vendor risk {v.vendor_risk}{flag}\n    {p.candidate.url}")
            print("    fit: " + ", ".join(f"{k}={x}" for k, x in p.requirement_fit.items()))
            for cv in v.verdicts:
                print(f"    - {cv.claim.field} = {cv.claim.value} {cv.claim.unit or ''}: {cv.verdict.upper()}")
                for e in cv.evidence:
                    print(f"        {e.engine:<22} {e.domain:<22} {e.note[:90]}")
            print(f"    risk: {v.vendor_risk_reason[:160]}")
            vp, m = v.vendor_profile, v.maturity
            if vp:
                age = f"{vp.domain_age_years} yrs (domain since {vp.domain_registered})" if vp.domain_registered else "unknown"
                print(f"    vendor: {vp.business_type}, founded {vp.founded_year or 'unknown'}, seller domain age {age}")
                print("    criteria: " + ", ".join(f"{c.criterion}={c.rating}" for c in vp.criteria))
            if m:
                print(f"    product: released {m.release_year or 'unknown'}, earliest independent mention "
                      f"{m.earliest_independent_mention or 'unknown'}, deployment: {m.deployment_level} "
                      f"({len(m.deployment)} examples)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report_path = args.report or args.out.with_name(args.out.stem + "_report.md")
    report_path.write_text(report.render(ranked, checklists, run.session_id, run.traces[n_before:], CRITERIA_HELP))
    args.out.write_text(json.dumps({
        "checklists": data["checklists"],
        "telem_session_id": run.session_id,
        "ranked": {k: [v.model_dump() for v in vs] for k, vs in ranked.items()},
        "traces": [t.model_dump() for t in run.traces],
    }, indent=2, default=str))
    print(f"\nSaved -> {args.out}\nReport -> {report_path}")


if __name__ == "__main__":
    main()
