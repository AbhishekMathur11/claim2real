"""Markdown report for verified candidates. Pure formatting: every finding comes from the verifier."""
from __future__ import annotations

from datetime import date

import config
from models import RequirementsChecklist, SearchTrace, Source, VerifiedCandidate

RATING = {"positive": "✅ positive", "neutral": "➖ neutral", "concern": "⚠️ concern", "unknown": "❔ unknown"}
VERDICT = {"verified": "✅ verified", "contradicted": "❌ contradicted", "unverified": "❔ unverified"}
FIT = {"meets": "✅ meets", "fails": "❌ fails", "unknown": "❔ unknown"}


def _cell(text) -> str:
    return str(text if text not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def _links(sources: list[Source], n: int = 3) -> str:
    seen, out = set(), []
    for s in sources:
        if s.url in seen:
            continue
        seen.add(s.url)
        out.append(f"[{s.domain}]({s.url})")
    return ", ".join(out[:n]) or "—"


def _req_line(r) -> str:
    return f"{r.field} {r.operator} {r.value}{' ' + r.unit if r.unit else ''}"


def _method(criteria_help: dict[str, str]) -> list[str]:
    w = (config.W_FIT, config.W_VERIFY, config.W_TRUST)
    lines = [
        "## How candidates were judged", "",
        "**Evidence.** Each candidate gets two batched Telem searches in the run's session (`auto_routing=accuracy`, "
        f"up to {config.VERIFY_MAX_ROUTING_PROVIDERS} providers per query): one about its claims (datasheet, price, "
        "stock, reviews, complaints) and one about the seller's history and real-world use of the product (builds, "
        "GitHub, forums). Tavily runs a second search for each must-have claim. Results from the seller's own domain "
        "and the vendor's own domain are discarded, so only independent sources count. The seller domain's "
        "registration date comes from the public RDAP registry.", "",
        "**Claim verdicts.** Claude compares each claim on the seller's page with the numbered independent evidence "
        "and may not use outside knowledge. Code then enforces these rules:",
        "- ✅ **verified** needs 2 or more independent domains stating the same value, or one authoritative source "
        "(a datasheet, manual or major distributor) plus one other item.",
        "- ❌ **contradicted** needs an independent item about this model giving a materially different value "
        "(>10% for numbers), or showing that the figure is peak rather than continuous, or that the interface "
        "is different.",
        "- ❔ **unverified** means neither rule was met; it is not a negative finding.", "",
        "**Vendor criteria.** Each one is rated positive / neutral / concern / unknown, with the finding and its sources:",
    ]
    lines += [f"- **{k}**: {v}." for k, v in criteria_help.items()]
    lines += [
        "", "The seller's own About/Contact pages (at most 2) are shown to Claude labelled *self-reported*. They can "
        "inform business type and contact details only; code stops them from supporting or contradicting any "
        "claim and from counting as independent footprint. *Spec accuracy* is set by code from the claim "
        "verdicts.", "",
        "Code checks can only make a rating worse: a seller domain younger than "
        f"{config.VERIFY_YOUNG_DOMAIN_YEARS:g} year is a *Time in market* concern, and a free-mail or mismatched "
        "contact domain is a *Contact* concern. The overall vendor risk is whichever is higher, Claude's rating "
        "or the code checks.", "",
        "**Time in market and real-world use.** The product's release year is taken from the evidence. The earliest "
        "independent mention is the oldest `publish_date` that Telem or Tavily returned for a page naming the model. "
        "Deployment examples are concrete builds, papers, integrations, reviews, forum threads or repos, each linked.", "",
        f"**Score** = {w[0]} × fit + {w[1]} × verification + {w[2]} × trust.",
        "- *fit*: the share of must-haves plus budget that the seller page meets (unknown counts as not met).",
        "- *verification*: (verified − contradicted) ÷ claims checked, never below 0.",
        "- *trust*: 1.0 for low vendor risk, 0.5 for medium, 0 for high.",
        "- A candidate that fails a must-have or is over budget is ranked below all the others.", "",
    ]
    return lines


def _candidate(i: int, v: VerifiedCandidate, c: RequirementsChecklist) -> list[str]:
    p, vp, m, b = v.profile, v.vendor_profile, v.maturity, v.score_breakdown
    flag = "" if v.meets_requirements else "  ·  ❌ does not meet requirements"
    out = [f"### {i}. {p.product_name or p.candidate.name}",
           f"Seller **{p.candidate.vendor}** ([{p.candidate.vendor_domain}]({p.candidate.url}))  ·  score "
           f"**{v.score:.2f}**  ·  vendor risk **{v.vendor_risk}**{flag}", ""]
    if v.recommendation:
        out += [f"> **Recommendation:** {v.recommendation}", ""]
    if b:
        out += ["**Score breakdown**", "",
                "| Component | Value | Weight | Contribution |", "|---|---|---|---|",
                f"| Requirement fit | {b['fit']:.2f} | {config.W_FIT} | {config.W_FIT * b['fit']:.3f} |",
                f"| Claim verification | {b['verification']:.2f} | {config.W_VERIFY} | "
                f"{config.W_VERIFY * b['verification']:.3f} |",
                f"| Vendor trust ({v.vendor_risk} risk) | {b['trust']:.2f} | {config.W_TRUST} | "
                f"{config.W_TRUST * b['trust']:.3f} |",
                f"| **Total** | | | **{b['total']:.3f}** |", ""]

    # Technical
    out += ["#### Technical: stated vs independent specs", "",
            "| Spec | Seller states | Independent sources say | Verdict | Sources |", "|---|---|---|---|---|"]
    for cv in v.verdicts:
        cl = cv.claim
        note = cv.evidence[0].note if cv.evidence else ""
        out.append(f"| {_cell(cl.field)} | {_cell(f'{cl.value} {cl.unit or ''}'.strip())} — “{_cell(cl.quote[:90])}” | "
                   f"{_cell(cv.independent_value)} | {VERDICT[cv.verdict]} | "
                   f"{_links([Source(url=e.url, domain=e.domain) for e in cv.evidence])} |")
        if note:
            out.append(f"| | | *{_cell(note[:220])}* | | |")
    if not v.verdicts:
        out.append("| — | no checkable claims on the seller page | | | |")
    out += ["", "| Requirement | Needed | Seller page |", "|---|---|---|"]
    for r in c.must_have + c.nice_to_have:
        tag = "" if r in c.must_have else " (nice-to-have)"
        out.append(f"| {r.field}{tag} | {_cell(_req_line(r))} | {FIT[p.requirement_fit.get(r.field, 'unknown')]} |")
    if c.budget_usd is not None:
        price = f"${p.price_usd:g}" if p.price_usd is not None else "no price"
        out.append(f"| budget | ≤ ${c.budget_usd:g} | {FIT[p.requirement_fit.get('budget_usd', 'unknown')]} ({price}) |")
    out.append("")
    if v.technical_summary:
        out += [v.technical_summary, ""]

    # Maturity
    if m:
        out += ["#### Product maturity and real-world use", ""]
        rel = (f"{m.release_year} ({_links(m.release_sources, 2)})" if m.release_year else "not stated in evidence")
        out.append(f"- **Released:** {rel}")
        if m.earliest_independent_mention:
            out.append(f"- **Earliest independent mention:** {m.earliest_independent_mention} "
                       f"({_links([m.earliest_mention_source], 1)})")
        else:
            out.append("- **Earliest independent mention:** no dated page found (search providers returned no "
                       "publish dates for this model)")
        out.append(f"- **Time on market:** {f'~{m.years_on_market:g} years' if m.years_on_market is not None else 'unknown'}")
        out.append(f"- **Real-world deployment:** {m.deployment_level}")
        for d in m.deployment:
            out.append(f"  - *{d.kind}*: {d.summary} ([{d.source.domain}]({d.source.url}))")
        out.append("")

    # Vendor
    if vp:
        out += ["#### Vendor assessment", ""]
        founded = f"{vp.founded_year} ({_links(vp.founded_sources, 2)})" if vp.founded_year else "not stated in evidence"
        dom = (f"{vp.domain} registered {vp.domain_registered} (~{vp.domain_age_years:g} years; registrar "
               f"{vp.domain_registrar or 'unknown'}; [RDAP]({vp.domain_source_url}))" if vp.domain_registered
               else f"{vp.domain}: registration date unavailable")
        out += [f"- **Business type:** {vp.business_type}", f"- **Founded:** {founded}", f"- **Seller domain:** {dom}"]
        if vp.manufacturer_note:
            out.append(f"- **Manufacturer:** {vp.manufacturer_note} ({_links(vp.manufacturer_sources)})")
        out += ["",
                "| Criterion | Rating | Finding | Sources |", "|---|---|---|---|"]
        for cr in vp.criteria:
            out.append(f"| {cr.criterion} | {RATING[cr.rating]} | {_cell(cr.detail)} | {_links(cr.sources)} |")
        out += ["", f"**Vendor risk: {v.vendor_risk}** — {v.vendor_risk_reason}", ""]
    if v.commercial_summary:
        out += [v.commercial_summary, ""]
    out += [f"<sub>{v.evidence_count} independent evidence items reviewed.</sub>", "", "---", ""]
    return out


def render(ranked: dict[str, list[VerifiedCandidate]], checklists: dict[str, RequirementsChecklist],
           session_id: str | None, traces: list[SearchTrace], criteria_help: dict[str, str]) -> str:
    tel = [t for t in traces if t.kind == "search"]
    tav = [t for t in traces if t.kind == "tavily"]
    lines = ["# Vendor and claim verification report", "",
             f"Generated {date.today()}  ·  Telem session `{session_id}`  ·  {len(tel)} Telem provider runs across "
             f"{len({t.provider for t in tel})} providers, {len(tav)} Tavily searches", ""]
    lines += _method(criteria_help)
    for comp, vcs in ranked.items():
        c = checklists[comp]
        lines += [f"## {comp}", ""]
        if c.problem_statement:
            lines += [f"*{c.problem_statement}*", ""]
        lines += ["**Must-haves:** " + "; ".join(_req_line(r) for r in c.must_have)
                  + (f"  ·  **Budget:** ${c.budget_usd:g}/unit" if c.budget_usd else "")
                  + (f"  ·  **Lead time:** ≤ {c.max_lead_time_days} days to {c.ship_to}" if c.max_lead_time_days else ""),
                  "", "| # | Product | Seller | Score | Risk | Verified / contradicted | Meets reqs |",
                  "|---|---|---|---|---|---|---|"]
        for i, v in enumerate(vcs, 1):
            nv = sum(x.verdict == "verified" for x in v.verdicts)
            nc = sum(x.verdict == "contradicted" for x in v.verdicts)
            lines.append(f"| {i} | {_cell(v.profile.product_name or v.profile.candidate.name)} | "
                         f"{_cell(v.profile.candidate.vendor)} | {v.score:.2f} | {v.vendor_risk} | "
                         f"{nv} / {nc} of {len(v.verdicts)} | {'yes' if v.meets_requirements else 'no'} |")
        lines.append("")
        for i, v in enumerate(vcs, 1):
            lines += _candidate(i, v, c)
    return "\n".join(lines)
