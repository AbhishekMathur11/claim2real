"""End-to-end sourcing workflow behind the UI.

Phase 1 - search (after "Start search"):
  open ONE Telem session for the run, then in parallel:
    hardware: discovery_agent per hardware requirement (all joining that session)
    software: software_agent discover over every software requirement
Phase 2 - verify (after "Start verification"), then the final agent automatically:
    hardware: catalog_agent -> verifier_agent per requirement (parallel chains)
    software: software_agent verify
    elimination (code, below) -> final list per requirement
    decision_agent: Build vs Buy per requirement
    final_agent: buyer briefing + people to contact + email drafts

Every agent folder has its own config/models/llm modules with the same names, so agents run as
subprocesses through their CLIs and hand off through JSON files in ui/data/runs/<run id>/.
Nothing here changes how an agent works.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS = Path(__file__).resolve().parent / "data" / "runs"
PARALLEL = 3          # hardware requirements processed at once
FINAL_PER_REQ = 3     # hardware candidates in each requirement's final list
LOG_LINES = 400

_UNIT = re.compile(r"_(nm|kg|v|w|rpm|mm_s|mm|n|a|hz|deg|c|h|tops|gb|usd)$")


def label(field: str) -> str:
    return "budget" if field == "budget_usd" else _UNIT.sub("", field).replace("_", " ")


def req_text(r: dict) -> str:
    unit = f" {r['unit']}" if r.get("unit") else ""
    op = {">=": "≥", "<=": "≤", "==": "=", "has": "has"}.get(r["operator"], r["operator"])
    return f"{label(r['field'])} {op} {r['value']}{unit}"


def need_text(r: dict) -> str:
    """'≥ 10 N·m' for a requirement row."""
    op = {">=": "≥", "<=": "≤", "==": "=", "has": ""}.get(r["operator"], r["operator"])
    unit = f" {r['unit']}" if r.get("unit") else ""
    return f"{op} {r['value']}{unit}".strip()


def _num(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


class Run:
    def __init__(self, spec: dict, limit: int | None = None):
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = RUNS / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.spec = spec
        self.limit = limit
        (self.dir / "spec.json").write_text(json.dumps(spec, indent=2))
        self.problem = ((spec.get("checklists") or [{}])[0] or {}).get("problem_statement", "")
        self.checklists = spec.get("checklists") or []
        self.software = self._software_reqs(spec)
        self.session_id: str | None = None
        self.session_traces: list[dict] = []
        self.sender: dict = {}
        self.phase = "search"
        self.state = "running"
        self.error: str | None = None
        self.started = time.time()
        self.steps = {k: {"state": "pending", "seconds": None} for k in ("search", "verify", "outreach")}
        self.hw = [{"search": "pending", "catalog": "pending", "verifier": "pending", "seconds": None}
                   for _ in self.checklists]
        self.sw = {"search": "pending", "verify": "pending"}
        self.files: dict[str, Path] = {}
        self.final: dict = {}
        self.buildbuy: dict[str, dict] = {}
        self.log: list[str] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._guard, args=(self._search,), daemon=True).start()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _software_reqs(spec: dict) -> list[str]:
        items = list(spec.get("software") or [])
        if not items:
            for c in spec.get("checklists") or []:
                items += c.get("software") or []
        seen, out = set(), []
        for s in items:
            s = str(s).strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        return out

    def _say(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            del self.log[:-LOG_LINES]

    def _exec(self, tag: str, folder: str, args: list[str]) -> int:
        proc = subprocess.Popen([sys.executable, *args], cwd=REPO / folder, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.strip():
                self._say(f"[{tag}] {line.rstrip()}")
        return proc.wait()

    def _load(self, key: str) -> dict | None:
        p = self.files.get(key)
        if p and p.exists():
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError:
                return None
        return None

    def _guard(self, fn) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - surface any orchestration failure to the UI
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
            self._say(f"[workflow] {self.error}")

    def _time(self, step: str, fn) -> None:
        self.steps[step]["state"] = "running"
        t0 = time.time()
        fn()
        self.steps[step]["seconds"] = round(time.time() - t0, 1)
        self.steps[step]["state"] = "done"

    # ------------------------------------------------------------------ phase 1: search

    def _open_session(self) -> None:
        """One Telem session per run, opened before any parallel call so every agent joins it."""
        from telem import Telem

        client = Telem(os.environ.get("TELEM_API_KEY"), base_url=os.environ.get("TELEM_BASE_URL"))
        parts = ", ".join([c.get("component_type", "") for c in self.checklists] + self.software[:6])
        goal = f"{self.problem} Source hardware and software for: {parts}."[:1500]
        resp = client.search(f"{self.problem[:200]} robot components", goal=goal, num_results=3,
                             context="open the sourcing session", auto_routing="accuracy")
        self.session_id = resp.session_id
        self.session_traces = [dict(stage="session", kind="search", query_or_url=r.query or "session",
                                    provider=r.provider, status=r.status, latency_ms=r.latency_ms,
                                    results=len(r.results), usage=None) for r in resp.by_provider]
        self._say(f"[workflow] Telem session {self.session_id}")

    def _search_hw(self, i: int) -> None:
        st = self.hw[i]
        st["search"] = "running"
        one = {**self.spec, "checklists": [self.checklists[i]]}
        spec_i = self.dir / f"spec_hw{i}.json"
        spec_i.write_text(json.dumps(one))
        out = self.dir / f"hw{i}_discovery.json"
        args = ["discovery.py", str(spec_i), "--out", str(out), "--session", self.session_id]
        if self.limit:
            args += ["-n", str(self.limit)]
        code = self._exec(f"hw{i}:discovery", "discovery_agent", args)
        self.files[f"hw{i}_discovery"] = out
        st["search"] = "done" if code == 0 and out.exists() else "error"

    def _search_sw(self) -> None:
        if not self.software:
            self.sw["search"] = "skipped"
            return
        self.sw["search"] = "running"
        out = self.dir / "sw_discovery.json"
        code = self._exec("software:discover", "software_agent",
                          ["software.py", "discover", str(self.dir / "spec.json"), "--out", str(out),
                           "--session", self.session_id])
        self.files["sw_discovery"] = out
        self.sw["search"] = "done" if code == 0 and out.exists() else "error"

    def _search(self) -> None:
        def body():
            self._open_session()
            with ThreadPoolExecutor(PARALLEL + 1) as ex:
                jobs = [ex.submit(self._search_hw, i) for i in range(len(self.checklists))]
                jobs.append(ex.submit(self._search_sw))
                for j in jobs:
                    j.result()
        self._time("search", body)
        self.phase, self.state = "search_done", "waiting"

    # ------------------------------------------------------------------ phase 2: verify + final

    def start_verify(self, sender: dict) -> None:
        if self.phase != "search_done":
            raise RuntimeError("search is not finished")
        self.sender = sender
        self.phase, self.state = "verify", "running"
        threading.Thread(target=self._guard, args=(self._verify,), daemon=True).start()

    def _verify_hw(self, i: int) -> None:
        st = self.hw[i]
        disc = self.files.get(f"hw{i}_discovery")
        if st["search"] != "done" or not disc:
            st["catalog"] = st["verifier"] = "skipped"
            return
        t0 = time.time()
        st["catalog"] = "running"
        cat = self.dir / f"hw{i}_catalog.json"
        code = self._exec(f"hw{i}:catalog", "catalog_agent", ["catalog.py", str(disc), "--out", str(cat)])
        self.files[f"hw{i}_catalog"] = cat
        st["catalog"] = "done" if code == 0 and cat.exists() else "error"
        if st["catalog"] != "done":
            st["verifier"] = "skipped"
            return
        st["verifier"] = "running"
        ver = self.dir / f"hw{i}_verified.json"
        rep = self.dir / f"hw{i}_report.md"
        code = self._exec(f"hw{i}:verifier", "verifier_agent",
                          ["verifier.py", str(cat), "--out", str(ver), "--report", str(rep)])
        self.files[f"hw{i}_verified"] = ver
        self.files[f"hw{i}_report"] = rep
        st["verifier"] = "done" if code == 0 and ver.exists() else "error"
        st["seconds"] = round(time.time() - t0, 1)

    def _verify_sw(self) -> None:
        disc = self.files.get("sw_discovery")
        if self.sw["search"] != "done" or not disc:
            self.sw["verify"] = "skipped"
            return
        self.sw["verify"] = "running"
        out = self.dir / "sw_verified.json"
        code = self._exec("software:verify", "software_agent", ["software.py", "verify", str(disc), "--out", str(out)])
        self.files["sw_verified"] = out
        self.sw["verify"] = "done" if code == 0 and out.exists() else "error"

    def _verify(self) -> None:
        def body():
            with ThreadPoolExecutor(PARALLEL + 1) as ex:
                jobs = [ex.submit(self._verify_hw, i) for i in range(len(self.checklists))]
                jobs.append(ex.submit(self._verify_sw))
                for j in jobs:
                    j.result()
            shortlist = self.final_lists()
            path = self.dir / "shortlist.json"
            path.write_text(json.dumps({"problem": self.problem, "requirements": [
                {"name": r["name"], "kind": r["kind"], "requirements": r.get("constraints", []),
                 "budget_usd": r.get("budget_usd"), "quantity": r.get("quantity"),
                 "kept": [_brief(c) for c in r["kept"]], "eliminated": [
                     {"name": c["name"], "reasons": c["reasons"]} for c in r["eliminated"]]}
                for r in shortlist]}, indent=2, default=str))
            out = self.dir / "buildbuy.json"
            self._exec("buildbuy", "decision_agent", ["buildbuy.py", str(path), "--out", str(out)])
            self.files["buildbuy"] = out
            data = self._load("buildbuy") or {}
            self.buildbuy = {r["requirement"]: r for r in data.get("recommendations", [])}
        self._time("verify", body)
        self.phase = "outreach"
        self._time("outreach", self._outreach)
        self.phase, self.state = "done", "done"

    def _outreach(self) -> None:
        md = self.dir / "final_input.md"
        md.write_text(self.final_input_markdown())
        out = self.dir / "final"
        sender = self.sender or {}
        code = self._exec("final", "final_agent", [
            "outreach.py", "--input", str(md), "--from-name", sender.get("name") or "[Your name]",
            "--from-company", sender.get("company") or "[Your company]",
            "--context", f"Sourcing for: {self.problem}"[:600], "--max-companies", "6", "--out", str(out)])
        self.files["final"] = out / "outreach.json"
        pack = self._load("final") or {}
        self.final = {"ok": code == 0 and bool(pack), "report": pack.get("report", ""),
                      "companies": pack.get("companies", []), "sender": pack.get("sender")}

    # ------------------------------------------------------------------ elimination (validation rules)

    def _hw_rows(self, i: int) -> list[dict]:
        ver = self._load(f"hw{i}_verified")
        if not ver:
            return []
        comp = self.checklists[i]["component_type"]
        rows = (ver.get("ranked") or {}).get(comp) or next(iter((ver.get("ranked") or {}).values()), [])
        return [_hw_card(v, self.checklists[i]) for v in rows]

    def final_lists(self) -> list[dict]:
        """Per requirement: kept (final list) and eliminated (with reasons), hardware then software."""
        out = []
        for i, c in enumerate(self.checklists):
            rows = self._hw_rows(i)
            kept = [r for r in rows if not r["reasons"]]
            for n, r in enumerate(kept):
                r["final"] = n < FINAL_PER_REQ
            out.append({"kind": "hardware", "index": i, "name": c["component_type"],
                        "constraints": [req_text(r) for r in c.get("must_have", [])],
                        "budget_usd": c.get("budget_usd"), "quantity": c.get("quantity"),
                        "kept": kept, "eliminated": [r for r in rows if r["reasons"]]})
        sw = (self._load("sw_verified") or {}).get("results") or {}
        for name in self.software:
            rows = [_sw_card(a) for a in sw.get(name, [])]
            out.append({"kind": "software", "name": name, "constraints": [],
                        "kept": [r for r in rows if not r["reasons"]],
                        "eliminated": [r for r in rows if r["reasons"]]})
        return out

    def final_input_markdown(self) -> str:
        """Compact verification report for the final agent: only the options that survived."""
        lines = ["# Vendor and claim verification report", "",
                 f"Problem: {self.problem}", f"Telem session `{self.session_id}`", ""]
        for r in self.final_lists():
            bb = self.buildbuy.get(r["name"])
            lines += [f"## {r['name']} ({r['kind']})", ""]
            if r["constraints"]:
                lines.append("**Must-haves:** " + "; ".join(r["constraints"])
                             + (f"  ·  **Budget:** ${_num(r['budget_usd'])}/unit" if r.get("budget_usd") else ""))
            if bb:
                lines.append(f"**Build vs buy:** {bb['decision']} — {bb['headline']}")
            lines += ["", "| # | Product | Company | Seller | Seller URL | Score | Risk | Verified / contradicted | Meets reqs | Recommendation |",
                      "|---|---|---|---|---|---|---|---|---|---|"]
            for n, k in enumerate([k for k in r["kept"] if k.get("final", True)][:FINAL_PER_REQ], 1):
                cell = lambda x: str(x if x not in (None, "") else "—").replace("|", "/").replace("\n", " ")
                lines.append(f"| {n} | {cell(k['name'])} | {cell(k.get('company'))} | {cell(k.get('vendor'))} | "
                             f"{cell(k['url'])} | {cell(k.get('score'))} | {cell(k.get('risk'))} | "
                             f"{cell(k.get('verified_summary'))} | yes | {cell(k.get('recommendation'))} |")
            if not r["kept"]:
                lines.append("| — | No option survived verification | | | | | | | no | |")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------ status for the UI

    def trace(self) -> dict:
        traces = list(self.session_traces)
        for i in range(len(self.checklists)):
            d = self._load(f"hw{i}_verified") or self._load(f"hw{i}_catalog") or self._load(f"hw{i}_discovery")
            traces += (d or {}).get("traces", [])
        d = self._load("sw_verified") or self._load("sw_discovery")
        traces += (d or {}).get("traces", [])
        telem = [t for t in traces if t["kind"] in ("search", "fetch")]
        by_stage: dict[str, dict] = {}
        for t in traces:
            s = by_stage.setdefault(t["stage"], {"search": 0, "fetch": 0, "tavily": 0, "latency_ms": 0})
            s[t["kind"]] += 1
            s["latency_ms"] += t.get("latency_ms") or 0
        return {"session_id": self.session_id, "telem_calls": len(telem),
                "tavily_calls": sum(t["kind"] == "tavily" for t in traces),
                "providers": dict(Counter(t["provider"] for t in telem if t["provider"] != "telem").most_common()),
                "errors": sum(str(t.get("status", "")).startswith("error") for t in traces), "by_stage": by_stage}

    def status(self) -> dict:
        hardware = []
        verified = self.phase in ("outreach", "done") or self.steps["verify"]["state"] == "done"
        finals = {(r["kind"], r["name"]): r for r in self.final_lists()} if self.phase != "search" else {}
        for i, c in enumerate(self.checklists):
            disc = self._load(f"hw{i}_discovery") or {}
            cands = next(iter((disc.get("candidates") or {}).values()), [])
            entry = {"index": i, "name": c["component_type"], "constraints": [req_text(r) for r in c.get("must_have", [])],
                     "budget_usd": c.get("budget_usd"), "quantity": c.get("quantity"), **self.hw[i],
                     "candidates": [{k: x.get(k) for k in ("name", "vendor", "url", "found_by_provider", "reason")}
                                    for x in cands]}
            if self.hw[i]["verifier"] == "done":
                f = finals.get(("hardware", c["component_type"]), {})
                entry.update(kept=f.get("kept", []), eliminated=f.get("eliminated", []))
            entry["buildbuy"] = self.buildbuy.get(c["component_type"]) if verified else None
            hardware.append(entry)
        swd = (self._load("sw_discovery") or {}).get("candidates") or {}
        software = []
        for name in self.software:
            entry = {"name": name, **self.sw, "candidates": swd.get(name, [])}
            if self.sw["verify"] == "done":
                f = finals.get(("software", name), {})
                entry.update(kept=f.get("kept", []), eliminated=f.get("eliminated", []))
            entry["buildbuy"] = self.buildbuy.get(name) if verified else None
            software.append(entry)
        with self._lock:
            log = self.log[-60:]
        return {"id": self.id, "problem": self.problem, "phase": self.phase, "state": self.state, "error": self.error,
                "elapsed": round(time.time() - self.started, 1), "steps": self.steps, "sender": self.sender,
                "hardware": hardware, "software": software, "outreach": self.final or None,
                "trace": self.trace() if self.session_id else None, "log": log}


# ---------------------------------------------------------------------- card builders

def _hw_card(v: dict, checklist: dict) -> dict:
    p, cand = v["profile"], v["profile"]["candidate"]
    must = {r["field"]: r for r in checklist.get("must_have", [])}
    fit = p.get("requirement_fit", {})
    claims = {cl["field"]: cl for cl in p.get("claims", [])}
    reasons = []
    for field, f in fit.items():
        if f != "fails":
            continue
        if field == "budget_usd":
            reasons.append(f"Over budget: ${_num(p.get('price_usd'))} vs ${_num(checklist.get('budget_usd'))}/unit")
        elif field in must:
            cl = claims.get(field, {})
            got = f"{_num(cl.get('value'))}{' ' + cl['unit'] if cl.get('unit') else ''}" if cl else "?"
            reasons.append(f"Fails {label(field)}: {got} (needs {need_text(must[field])})")
    for vd in v.get("verdicts", []):
        if vd["verdict"] == "contradicted" and vd["claim"]["field"] in must:
            reasons.append(f"{label(vd['claim']['field']).capitalize()} contradicted by independent sources")
    if v.get("vendor_risk") == "high":
        reasons.append("High vendor risk: " + (v.get("vendor_risk_reason") or "")[:140])
    if not any(fit.get(f) == "meets" for f in must):
        reasons.append("No must-have spec confirmed on the vendor page"
                       + (" (page unreadable)" if p.get("page_status") != "ok" else ""))
    nv = sum(x["verdict"] == "verified" for x in v.get("verdicts", []))
    nc = sum(x["verdict"] == "contradicted" for x in v.get("verdicts", []))
    vp, m = v.get("vendor_profile") or {}, v.get("maturity") or {}
    return {
        "name": p.get("product_name") or cand["name"], "vendor": cand["vendor"], "url": cand["url"],
        "company": (vp.get("manufacturer_note") or "").split(",")[0][:60] or None,
        "found_by": cand.get("found_by_provider"), "engine": p.get("extraction_engine"),
        "price_usd": p.get("price_usd"), "availability": p.get("availability"), "fit": fit,
        "score": v.get("score"), "breakdown": v.get("score_breakdown") or {}, "risk": v.get("vendor_risk"),
        "risk_reason": v.get("vendor_risk_reason"), "meets": v.get("meets_requirements"),
        "recommendation": v.get("recommendation") or "", "technical_summary": v.get("technical_summary") or "",
        "verified_summary": f"{nv} verified / {nc} contradicted of {len(v.get('verdicts', []))}",
        "business_type": vp.get("business_type"), "founded_year": vp.get("founded_year"),
        "domain_age_years": vp.get("domain_age_years"), "release_year": m.get("release_year"),
        "deployment_level": m.get("deployment_level"),
        "verdicts": [{"field": x["claim"]["field"], "label": label(x["claim"]["field"]), "value": x["claim"]["value"],
                      "unit": x["claim"].get("unit"), "quote": x["claim"].get("quote"), "verdict": x["verdict"],
                      "independent_value": x.get("independent_value"), "evidence": x.get("evidence", [])}
                     for x in v.get("verdicts", [])],
        "reasons": reasons,
    }


def _sw_card(a: dict) -> dict:
    c = a["candidate"]
    return {"name": c["name"], "vendor": c["provider"], "company": c["provider"], "url": c["url"], "kind": c.get("kind"),
            "license": a.get("license"), "cost_model": a.get("cost_model"), "maintenance": a.get("maintenance"),
            "maturity": a.get("maturity"), "integration": a.get("integration"), "fit": a.get("fit"),
            "validation": a.get("validation"), "rank": a.get("rank"), "reason": a.get("reason"),
            "recommendation": a.get("reason") if a.get("decision") == "keep" else "",
            "verified_summary": a.get("validation"), "risk": "", "score": None, "sources": a.get("sources", []),
            "found_by": c.get("found_by_provider"),
            "reasons": [] if a.get("decision") == "keep" else [a.get("reason") or "Eliminated by validation"]}


def _brief(c: dict) -> dict:
    keys = ("name", "vendor", "price_usd", "score", "risk", "verified_summary", "recommendation", "license",
            "cost_model", "maintenance", "maturity", "fit", "validation", "deployment_level", "release_year")
    return {k: c.get(k) for k in keys if c.get(k) not in (None, "", [])}


# ---------------------------------------------------------------------- registry

RUNS_BY_ID: dict[str, Run] = {}


def start(spec: dict, limit: int | None = None) -> Run:
    run = Run(spec, limit)
    RUNS_BY_ID[run.id] = run
    return run


def latest() -> Run | None:
    return RUNS_BY_ID[max(RUNS_BY_ID)] if RUNS_BY_ID else None
