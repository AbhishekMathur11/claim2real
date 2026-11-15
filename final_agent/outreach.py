#!/usr/bin/env python3
"""Find outreach contacts at hardware/software vendors and draft emails."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

from models import (
    Candidate,
    CompanyOutreach,
    DraftEmail,
    OutreachInput,
    OutreachPack,
    ParsedFindings,
    Person,
    Sender,
    Target,
)
import tavily_people
from llm import call_json, call_text

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"


class PeopleOut(BaseModel):
    people: list[Person] = Field(default_factory=list)


class EmailsOut(BaseModel):
    emails: list[DraftEmail] = Field(default_factory=list)


PEOPLE_SYS = """You extract outreach contacts for a robotics buyer.
Use only the evidence. Never invent a person, title, email, or LinkedIn URL.
Prefer people who can take a sales/partnership/product conversation:
founders, CEO, VP/Head of Sales, BD, partnerships, product, applications engineering.
Skip generic press names with no role at this company.
At most 6 people. email only if a page shows it. linkedin only if a URL is present.
source_url must be one of the evidence URLs.
JSON: {"people":[...]}"""

EMAIL_SYS = """Write short outreach emails a hardware buyer would actually send.
Sign as the given sender name and sender company only.
Never mention claim2real unless that is the sender company.
If they are the manufacturer, ask about datasheet, variant, and authorization.
If they are the seller, ask about quote, stock, datasheet, and business registration when risk is medium/high.
Use spec contradictions (peak vs continuous, 12 N·m vs 9 N·m) when they are in the notes.
Plain text, 80–120 words, no hype, no fake familiarity.
Do not invent email addresses.
JSON: {"emails":[{"to_name","to_title","subject","body"}]}"""

PARSE_SYS = """Parse a Vendor and claim verification report.
company = manufacturer (DAMIAO, MyActuator, Realman), never the marketplace.
seller = the listing seller (ZennixTek, RobotShop, NanoVolt).
meets_reqs true for yes/✅, false for no/❌.
Keep recommendation, risk, verified_contradicted, seller_url.
JSON: {"problem":"","must_haves":"","budget":"","candidates":[{"rank","product","company","seller","seller_url","score","risk","meets_reqs","verified_contradicted","verdicts","recommendation","notes":""}],"highlights":[]}"""

REPORT_SYS = """The input is a Vendor and claim verification report (independent Telem/Tavily evidence, claim verdicts, vendor-risk ratings).
Write a buyer-facing briefing in markdown. Do not invent evidence. Do not change verdicts.
Use the report's language: verified / contradicted / unverified, and vendor risk low/medium/high.
Include:
1. What was bought-against (must-haves, budget, lead time)
2. Ranking table (product, seller, manufacturer, score, risk, meets reqs)
3. Spec traps worth a demo (contradictions, peak vs continuous, missing mass/price)
4. Vendor risk (new domains vs established sellers vs manufacturer)
5. Who to contact next and why — manufacturer for specs/authorization, seller for quote/stock/datasheet
Keep citations from the source report. No email drafts."""


def _sender_from(data: dict, from_name: str, from_company: str, context: str) -> Sender:
    sender = dict(data.get("sender") or {})
    if from_name:
        sender["name"] = from_name
    if from_company:
        sender["company"] = from_company
    if context:
        sender["context"] = context
    if not str(sender.get("name") or "").strip() or not str(sender.get("company") or "").strip():
        sys.exit("Pass --from-name and --from-company (the person and company sending these emails)")
    return Sender.model_validate(sender)


def _read_blob(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}, text
    if isinstance(data, list):
        return {"targets": data}, text
    if not isinstance(data, dict):
        return {}, text
    findings = data.get("findings") or data.get("report") or data.get("table")
    extra = findings if isinstance(findings, str) else ""
    return data, extra or (text if not data.get("targets") else "")


def parse_findings(raw: str) -> ParsedFindings:
    return call_json(PARSE_SYS, raw[:50000], ParsedFindings, max_tokens=16000)


def write_report(sender: Sender, raw: str, parsed: ParsedFindings) -> str:
    user = (
        f"Buyer: {sender.name} at {sender.company}. {sender.context}\n\n"
        f"Structured candidates:\n{parsed.model_dump_json(indent=2)}\n\n"
        f"Original verification report:\n{raw[:45000]}"
    )
    return call_text(REPORT_SYS, user, max_tokens=8192)


def _merge_target(
    grouped: dict[str, Target],
    name: str,
    cand: Candidate,
    role: str,
    domain: str | None,
) -> None:
    key = name.strip()
    if not key:
        return
    note = " | ".join(
        part
        for part in (
            cand.verified_contradicted and f"claims {cand.verified_contradicted}",
            cand.verdicts,
            cand.recommendation,
        )
        if part
    )
    if key not in grouped:
        grouped[key] = Target(
            company=key,
            domain=domain,
            products=[cand.product] if cand.product else [],
            verdicts=note,
            score=cand.score,
            meets_reqs=cand.meets_reqs,
            role=role,
            risk=cand.risk,
            recommendation=cand.recommendation,
        )
        return
    item = grouped[key]
    if cand.product and cand.product not in item.products:
        item.products.append(cand.product)
    if note:
        item.verdicts = (item.verdicts + " " + note).strip()
    if cand.meets_reqs:
        item.meets_reqs = True
    if not item.domain and domain:
        item.domain = domain


def targets_from_findings(parsed: ParsedFindings, limit: int) -> list[Target]:
    grouped: dict[str, Target] = {}
    ordered: list[Candidate] = sorted(
        parsed.candidates,
        key=lambda c: (c.meets_reqs is not True, -(c.score or 0)),
    )
    for cand in ordered:
        manufacturer = (cand.company or "").strip()
        seller = (cand.seller or "").strip()
        domain = None
        if cand.seller_url:
            host = cand.seller_url.replace("https://", "").replace("http://", "").split("/")[0]
            domain = host or None
        if manufacturer:
            _merge_target(grouped, manufacturer, cand, "manufacturer", None)
        if seller and seller.lower() not in manufacturer.lower():
            _merge_target(grouped, seller, cand, "seller", domain)
        if len(grouped) >= limit:
            break
    return list(grouped.values())[:limit]


def load_input(
    path: Path | None,
    vendor: str,
    products: list[str],
    from_name: str,
    from_company: str,
    context: str,
    max_companies: int,
) -> tuple[OutreachInput, ParsedFindings | None, str]:
    data: dict = {}
    findings_text = ""
    if path:
        data, findings_text = _read_blob(path)
    elif vendor:
        data = {"targets": [{"company": vendor, "products": products}]}
    else:
        sys.exit("Pass --input or --company")
    sender = _sender_from(data, from_name, from_company, context)
    parsed = parse_findings(findings_text) if findings_text.strip() else None
    if parsed and parsed.candidates:
        targets = targets_from_findings(parsed, max_companies)
    elif data.get("targets"):
        targets = [Target.model_validate(row) for row in data["targets"]]
    else:
        sys.exit("No companies found in the input")
    if context and not sender.context:
        sender.context = context
    if parsed and parsed.problem and not sender.context:
        sender.context = parsed.problem
    return OutreachInput(sender=sender, targets=targets), parsed, findings_text


def extract_people(target: Target, evidence: str) -> list[Person]:
    user = (
        f"Company: {target.company}\n"
        f"Domain: {target.domain or ''}\n"
        f"Products: {', '.join(target.products) or 'unspecified'}\n"
        f"Kind: {target.kind or ''}\n\n"
        f"Evidence:\n{evidence[:24000]}"
    )
    out = call_json(PEOPLE_SYS, user, PeopleOut)
    people = []
    for person in out.people:
        person.company = target.company
        if not person.why_reach_out:
            person.why_reach_out = person.title or "Listed on the company leadership/sales pages"
        if person.email and "@" not in person.email:
            person.email = None
        people.append(person)
    return people[:6]


def draft_emails(sender: Sender, target: Target, people: list[Person]) -> list[DraftEmail]:
    if not people:
        return []
    roster = [
        {"name": p.name, "title": p.title, "why": p.why_reach_out} for p in people
    ]
    user = (
        f"Sender name: {sender.name}\n"
        f"Sender company: {sender.company}\n"
        f"Why they are reaching out: {sender.context}\n"
        f"This contact is the {target.role or 'vendor'} {target.company}.\n"
        f"Products: {', '.join(target.products) or 'their hardware/software'}.\n"
        f"Vendor risk: {target.risk or 'n/a'}. Meets requirements: {target.meets_reqs}.\n"
        f"Verification notes: {target.verdicts or 'n/a'}\n"
        f"Suggested ask: {target.recommendation or 'datasheet, quote, lead time'}\n"
        f"People:\n{json.dumps(roster, indent=2)}\n"
        f"Sign every email as {sender.name}, {sender.company}. "
        "One email per person, in the same order."
    )
    out = call_json(EMAIL_SYS, user, EmailsOut)
    return out.emails[: len(people)]


def run_target(sender: Sender, target: Target) -> CompanyOutreach:
    queries, hits = asyncio.run(tavily_people.search_company(target))
    urls = tavily_people.pick_urls(hits)
    pages = tavily_people.extract_pages(urls)
    evidence = tavily_people.evidence_block(hits, pages)
    people = extract_people(target, evidence) if evidence.strip() else []
    emails = draft_emails(sender, target, people)
    return CompanyOutreach(
        company=target.company,
        domain=target.domain,
        products=target.products,
        role=target.role,
        risk=target.risk,
        people=people,
        emails=emails,
        queries=queries,
        sources=urls,
    )


def _safe_run_target(sender: Sender, target: Target) -> CompanyOutreach:
    """One company's failure (search, people or drafts) must not drop every other company's outreach."""
    try:
        return run_target(sender, target)
    except BaseException as exc:  # noqa: BLE001 - call_json raises SystemExit on bad JSON
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"[outreach] {target.company}: skipped ({str(exc).splitlines()[0][:160]})", file=sys.stderr, flush=True)
        return CompanyOutreach(company=target.company, domain=target.domain, products=target.products,
                               role=target.role, risk=target.risk, people=[], emails=[], queries=[], sources=[])


def to_markdown(pack: OutreachPack) -> str:
    lines = [
        "# Outreach pack",
        "",
        f"From **{pack.sender.name}**, {pack.sender.company}",
        "",
    ]
    for company in pack.companies:
        lines += [f"## {company.company}", ""]
        if company.products:
            lines.append("Products: " + ", ".join(company.products))
        meta = [x for x in (company.role, company.risk and f"risk {company.risk}") if x]
        if meta:
            lines.append(" · ".join(meta))
        if company.products or meta:
            lines.append("")
        if not company.people:
            lines += ["No sourced contacts.", ""]
            continue
        lines += ["### People", ""]
        for person in company.people:
            contact = person.email or person.linkedin or person.source_url
            lines.append(f"- **{person.name}** — {person.title}")
            lines.append(f"  Why: {person.why_reach_out}")
            lines.append(f"  Reach: {contact}")
            if person.source_note:
                lines.append(f"  Source: {person.source_note} ({person.source_url})")
            else:
                lines.append(f"  Source: {person.source_url}")
        lines += ["", "### Draft emails", ""]
        for mail in company.emails:
            lines += [
                f"#### To {mail.to_name} ({mail.to_title})",
                f"**Subject:** {mail.subject}",
                "",
                mail.body.strip(),
                "",
            ]
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Markdown/text findings table, or JSON")
    parser.add_argument("--from-name", default="", help="Your name, as signed on the emails")
    parser.add_argument("--from-company", default="", help="Your company, as signed on the emails")
    parser.add_argument("--context", default="", help="Why you are reaching out")
    parser.add_argument("--company", default="", help="Vendor company to research")
    parser.add_argument("--product", action="append", default=[])
    parser.add_argument("--max-companies", type=int, default=6)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    spec, parsed, findings_text = load_input(
        args.input,
        args.company,
        args.product,
        args.from_name,
        args.from_company,
        args.context,
        args.max_companies,
    )
    # The briefing and every company's people search + drafts are independent: run them all at once.
    with ThreadPoolExecutor(max_workers=len(spec.targets) + 1) as pool:
        report_job = (pool.submit(write_report, spec.sender, findings_text, parsed)
                      if findings_text.strip() and parsed else None)
        company_jobs = [pool.submit(_safe_run_target, spec.sender, target) for target in spec.targets]
        companies = [job.result() for job in company_jobs]
        report = report_job.result() if report_job else ""
    pack = OutreachPack(
        sender=spec.sender,
        report=report,
        findings=parsed,
        companies=companies,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "outreach.json").write_text(pack.model_dump_json(indent=2) + "\n")
    if report:
        (args.out / "report.md").write_text(report.rstrip() + "\n")
    md = to_markdown(pack)
    (args.out / "outreach.md").write_text(md)
    print((report + "\n\n" if report else "") + md)
    wrote = [args.out / "outreach.md"]
    if report:
        wrote.insert(0, args.out / "report.md")
    print("\nWrote " + ", ".join(str(p) for p in wrote), file=sys.stderr)


if __name__ == "__main__":
    main()
