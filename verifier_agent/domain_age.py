"""Domain registration date via public RDAP (no API key), as a hard "time in market" signal.

rdap.org redirects to the registry's RDAP server for the TLD. Failures return None; the
report then says the registration date is unknown.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime
from functools import lru_cache

from pydantic import BaseModel

RDAP_URL = "https://rdap.org/domain/{}"
TIMEOUT_S = 8


class DomainAge(BaseModel):
    domain: str
    registered: date | None = None
    registrar: str | None = None
    source_url: str

    @property
    def years_exact(self) -> float | None:
        return (date.today() - self.registered).days / 365.25 if self.registered else None

    @property
    def years(self) -> float | None:
        """Rounded for display; compare thresholds against years_exact."""
        return round(self.years_exact, 1) if self.registered else None


@lru_cache(maxsize=256)
def lookup(domain: str) -> DomainAge | None:
    if not domain:
        return None
    url = RDAP_URL.format(domain)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/rdap+json", "User-Agent": "claim-verifier"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - fixed https host
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - unknown TLD, rate limit, network: just "unknown"
        return None
    registered = None
    for ev in data.get("events", []):
        if ev.get("eventAction") == "registration" and ev.get("eventDate"):
            try:
                registered = datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00")).date()
            except ValueError:
                pass
    registrar = None
    for ent in data.get("entities", []):
        if "registrar" in (ent.get("roles") or []):
            for item in (ent.get("vcardArray") or [None, []])[1]:
                if item and item[0] == "fn":
                    registrar = item[3]
    return DomainAge(domain=domain, registered=registered, registrar=registrar, source_url=url)
