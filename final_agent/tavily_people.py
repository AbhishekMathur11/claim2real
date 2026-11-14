"""Tavily search + extract for company leadership and sales contacts."""

from __future__ import annotations

import asyncio
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


async def _search_one(client: AsyncTavilyClient, query: str) -> list[dict[str, Any]]:
    try:
        resp = await client.search(
            query=query,
            search_depth="advanced",
            max_results=10,
        )
        return resp.get("results") or []
    except Exception:
        return []


async def search_company(target: Target) -> tuple[list[str], list[dict[str, Any]]]:
    qs = queries_for(target)
    client = _async_client()
    batches = await asyncio.gather(*[_search_one(client, q) for q in qs])
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
    except Exception:
        return []


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
