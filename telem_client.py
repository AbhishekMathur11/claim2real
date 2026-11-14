"""Telem wrapper: one session per sourcing run, trace capture on every call."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from telem import Telem, TelemError
from telem.models import SearchResponse

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
