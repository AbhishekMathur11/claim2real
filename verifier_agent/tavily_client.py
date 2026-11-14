"""Tavily wrappers: extraction fallback (Catalog reader) and second-opinion search (Verifier).

Every call records a SearchTrace(kind="tavily") on the run so the UI lists Tavily separately.
"""
from __future__ import annotations

import time
from typing import Any

from tavily import TavilyClient

import config
from models import SearchTrace

_client: TavilyClient | None = None


def _get() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(config.TAVILY_API_KEY)
    return _client


def extract(url: str, traces: list[SearchTrace], stage: str) -> tuple[str, str]:
    """Return (markdown content, title) for one URL; ("", "") on failure."""
    t0 = time.monotonic()
    try:
        resp = _get().extract([url], extract_depth="advanced", format="markdown")
        rows = resp.get("results") or []
        content = (rows[0].get("raw_content") or "") if rows else ""
        status = "succeeded" if content else "failed"
    except Exception as e:  # noqa: BLE001
        content, status = "", f"error: {type(e).__name__}: {e}"[:300]
    traces.append(SearchTrace(stage=stage, kind="tavily", query_or_url=url, provider="tavily-extract",
                              status=status, latency_ms=int((time.monotonic() - t0) * 1000),
                              results=1 if content else 0))
    return content, ""


def search(query: str, traces: list[SearchTrace], stage: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Advanced Tavily search. Returns [{url, title, content}] ([] on failure)."""
    t0 = time.monotonic()
    try:
        resp = _get().search(query, search_depth="advanced", max_results=max_results)
        rows = resp.get("results") or []
        status = "succeeded"
    except Exception as e:  # noqa: BLE001
        rows, status = [], f"error: {type(e).__name__}: {e}"[:300]
    traces.append(SearchTrace(stage=stage, kind="tavily", query_or_url=query, provider="tavily-search",
                              status=status, latency_ms=int((time.monotonic() - t0) * 1000), results=len(rows)))
    return rows
