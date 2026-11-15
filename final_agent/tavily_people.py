"""Tavily search + extract for company leadership and sales contacts, with Telem as the fallback.

If Tavily fails (e.g. the plan's usage limit is exceeded), the same queries go through one batched
Telem search and the chosen pages through Telem fetch, so outreach still finds people. Errors are
printed to stderr (shown in the UI log) instead of silently producing zero people.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from tavily import AsyncTavilyClient, TavilyClient

import config
from models import Target

TEAM_HINTS = (
    "team",
    "leadership",
    "about",
    "management",
    "founder",
    "linkedin.com/in/",
    "linkedin.com/company/",
    "press",
    "newsroom",
)


def _client() -> TavilyClient:
    return TavilyClient(api_key=config.tavily_key())


def _async_client() -> AsyncTavilyClient:
    return AsyncTavilyClient(api_key=config.tavily_key())


def queries_for(target: Target) -> list[str]:
    name = target.company.strip()
    product = (target.products or ["industrial robot"])[0]
    rows = [
        f"{name} leadership team CEO founder",
        f"{name} VP sales partnerships business development",
        f"{name} {product} product manager applications engineer",
        f"{name} contact sales robotics",
    ]
    if target.domain:
        host = target.domain.replace("https://", "").replace("http://", "").split("/")[0]
        rows.append(f"site:{host} team leadership")
    return rows[:5]


def _warn(msg: str) -> None:
    print(f"[outreach] {msg}", file=sys.stderr, flush=True)


def _telem():
    from telem import Telem  # lazy: only needed on fallback

    key = os.getenv("TELEM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TELEM_API_KEY not set")
    return Telem(key, base_url=os.getenv("TELEM_BASE_URL") or "https://router.telem.ai")


def _telem_search(qs: list[str], company: str) -> list[list[dict[str, Any]]]:
    """One batched Telem search; returns rows shaped like Tavily's {url, title, content}, per query."""
    try:
        resp = _telem().search(qs if len(qs) > 1 else qs[0], context=f"find leadership and sales contacts at {company}",
                               auto_routing="accuracy", max_routing_providers=3, num_results=8)
    except Exception as e:  # noqa: BLE001
        _warn(f"Telem fallback search failed for {company}: {type(e).__name__}: {str(e)[:160]}")
        return [[] for _ in qs]
    out: list[list[dict[str, Any]]] = [[] for _ in qs]
    for run in resp.by_provider:
        i = min(run.batch_index or 0, len(qs) - 1)
        for r in run.results:
            out[i].append({"url": r.url, "title": r.title or "", "content": r.summary or " ".join(r.excerpt or [])})
    return out


async def _search_one(client: AsyncTavilyClient, query: str) -> list[dict[str, Any]] | None:
    """Tavily results, or None when the call failed (so the caller can fall back)."""
    try:
        resp = await client.search(
            query=query,
            search_depth="advanced",
            max_results=10,
        )
        return resp.get("results") or []
    except Exception as e:  # noqa: BLE001
        _warn(f"Tavily search failed ({type(e).__name__}: {str(e)[:120]})")
        return None


async def search_company(target: Target) -> tuple[list[str], list[dict[str, Any]]]:
    qs = queries_for(target)
    client = _async_client()
    batches = await asyncio.gather(*[_search_one(client, q) for q in qs])
    failed = [q for q, b in zip(qs, batches) if b is None]
    if failed:
        _warn(f"using Telem for {len(failed)} people searches for {target.company}")
        redo = iter(await asyncio.to_thread(_telem_search, failed, target.company))
        batches = [next(redo) if b is None else b for b in batches]
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for batch in batches:
        for row in batch:
            url = (row.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            hits.append(row)
    return qs, hits


def pick_urls(hits: list[dict[str, Any]], limit: int = 8) -> list[str]:
    scored: list[tuple[int, str]] = []
    for row in hits:
        url = (row.get("url") or "").lower()
        title = (row.get("title") or "").lower()
        blob = f"{url} {title}"
        score = sum(1 for hint in TEAM_HINTS if hint in blob)
        if "linkedin.com/in/" in url:
            score += 2
        scored.append((score, row.get("url") or ""))
    scored.sort(key=lambda item: item[0], reverse=True)
    urls = [url for score, url in scored if url]
    return urls[:limit]


def extract_pages(urls: list[str]) -> list[dict[str, Any]]:
    if not urls:
        return []
    try:
        resp = _client().extract(urls[:20], extract_depth="advanced")
        return resp.get("results") or []
    except Exception as e:  # noqa: BLE001
        _warn(f"Tavily extract failed ({type(e).__name__}: {str(e)[:120]}); using Telem fetch")
    pages: list[dict[str, Any]] = []
    client = None
    for i in range(0, min(len(urls), 10), 5):  # Telem fetch takes at most 5 URLs per call
        try:
            client = client or _telem()
            resp = client.fetch(urls[i:i + 5], content_format="markdown", inline_content=True, inline_max_chars=6000)
            pages += [{"url": r.url, "raw_content": r.content or ""} for r in resp.results if r.content]
        except Exception as e:  # noqa: BLE001
            _warn(f"Telem fetch failed: {type(e).__name__}: {str(e)[:160]}")
    return pages


def evidence_block(hits: list[dict[str, Any]], pages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for row in hits[:18]:
        title = row.get("title") or ""
        url = row.get("url") or ""
        content = (row.get("content") or "")[:800]
        chunks.append(f"SEARCH {title}\n{url}\n{content}")
    for page in pages:
        url = page.get("url") or ""
        raw = (page.get("raw_content") or "")[:4000]
        if raw:
            chunks.append(f"PAGE {url}\n{raw}")
    return "\n\n---\n\n".join(chunks)
