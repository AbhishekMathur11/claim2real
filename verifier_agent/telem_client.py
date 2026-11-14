"""Telem wrapper: one session per sourcing run, trace capture on every call."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from telem import AsyncTelem, Telem, TelemError
from telem.models import FetchResult, SearchResponse

import config
from models import SearchTrace


@dataclass
class TelemRun:
    """Holds the Telem client, the run's session id and every trace recorded in the run."""

    goal: str | None = None
    session_id: str | None = None
    traces: list[SearchTrace] = field(default_factory=list)
    discovery_plans: dict[str, Any] = field(default_factory=dict)  # component_type -> query plan
    client: Telem = field(default_factory=lambda: Telem(config.TELEM_API_KEY, base_url=config.TELEM_BASE_URL))

    def search(self, stage: str, queries: str | Sequence[str], *, context: str, **kwargs: Any) -> SearchResponse | None:
        """Run one (possibly batched) Telem search in this run's session.

        The first call of a run sends `goal` and opens the session. Returns None on failure
        (recorded as a trace) so callers can continue.
        """
        q_list = [queries] if isinstance(queries, str) else list(queries)
        params: dict[str, Any] = {"context": context, **kwargs}
        if self.session_id:
            params["session"] = self.session_id
        elif self.goal:
            params["goal"] = self.goal
        try:
            resp = self.client.search(q_list if len(q_list) > 1 else q_list[0], **params)
        except TelemError as e:
            for q in q_list:
                self.traces.append(SearchTrace(stage=stage, kind="search", query_or_url=q, provider="telem",
                                               status=f"error: {type(e).__name__}: {e}"[:300], latency_ms=None, results=0))
            return None
        self.session_id = self.session_id or resp.session_id
        for run in resp.by_provider:
            self.traces.append(SearchTrace(
                stage=stage, kind="search",
                query_or_url=run.query or q_list[min(run.batch_index, len(q_list) - 1)],
                provider=run.provider, status=run.status, latency_ms=run.latency_ms,
                results=len(run.results), usage=run.usage,
            ))
        return resp

    def fetch(self, stage: str, urls: Sequence[str], *, chunk: int = 5, **kwargs: Any) -> dict[str, FetchResult]:
        """Fetch URLs in chunks within this run's session. Returns {requested url: FetchResult}.

        Failed URLs (server-side or a whole-chunk exception) map to a FetchResult with
        status starting "error"/"failed" and no content, so callers can fall back per URL.
        """
        out: dict[str, FetchResult] = {}
        urls = list(dict.fromkeys(urls))
        for i in range(0, len(urls), chunk):
            batch = urls[i:i + chunk]
            params: dict[str, Any] = dict(kwargs)
            if self.session_id:
                params["session"] = self.session_id
            try:
                resp = self.client.fetch(batch, **params)
                self.session_id = self.session_id or resp.session_id
                rows = list(resp.results)
            except TelemError as e:
                rows = [FetchResult(url=u, status=f"error: {type(e).__name__}: {e}"[:300], batch_index=j)
                        for j, u in enumerate(batch)]
            for j, u in enumerate(batch):
                # Results come back in request order; fall back to batch_index if lengths differ.
                r = rows[j] if j < len(rows) else next((x for x in rows if x.batch_index == j), None)
                r = r or FetchResult(url=u, status="failed: no result row", batch_index=j)
                out[u] = r
                self.traces.append(SearchTrace(
                    stage=stage, kind="fetch", query_or_url=u, provider=r.provider or "telem",
                    status=r.status or ("succeeded" if r.content else "failed"),
                    latency_ms=r.latency_ms, results=1 if r.content else 0,
                ))
        return out

    async def asearch(self, client: AsyncTelem, stage: str, queries: Sequence[str], *, context: str,
                      **kwargs: Any) -> SearchResponse | None:
        """Async batched search in this run's session (for parallel per-candidate work).

        The session must already be open (Discovery opened it), so parallel calls all join it
        instead of each starting a new one.
        """
        if not self.session_id:
            raise RuntimeError("asearch needs an open session; run a synchronous search first")
        q_list = list(queries)
        try:
            resp = await client.search(q_list if len(q_list) > 1 else q_list[0], context=context,
                                       session=self.session_id, **kwargs)
        except TelemError as e:
            for q in q_list:
                self.traces.append(SearchTrace(stage=stage, kind="search", query_or_url=q, provider="telem",
                                               status=f"error: {type(e).__name__}: {e}"[:300], latency_ms=None, results=0))
            return None
        for run in resp.by_provider:
            self.traces.append(SearchTrace(
                stage=stage, kind="search",
                query_or_url=run.query or q_list[min(run.batch_index, len(q_list) - 1)],
                provider=run.provider, status=run.status, latency_ms=run.latency_ms,
                results=len(run.results), usage=run.usage,
            ))
        return resp


def async_client() -> AsyncTelem:
    return AsyncTelem(config.TELEM_API_KEY, base_url=config.TELEM_BASE_URL)
