"""Settings loaded from .env plus tunable constants."""
import os

from dotenv import load_dotenv

load_dotenv()

TELEM_API_KEY = os.getenv("TELEM_API_KEY")
TELEM_BASE_URL = os.getenv("TELEM_BASE_URL", "https://router.telem.ai")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Same variable name as requirements_agent; LLM_MODEL kept as a fallback.
LLM_MODEL = os.getenv("OPENROUTER_MODEL") or os.getenv("LLM_MODEL") or "anthropic/claude-sonnet-5.5"
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"

# Distributor / marketplace hosts for the scoped discovery search (Telem caps at 20).
DISTRIBUTOR_DOMAINS = [
    "digikey.com",
    "mouser.com",
    "robotshop.com",
    "aliexpress.com",
    "alibaba.com",
    "amazon.com",
    "servocity.com",
    "pololu.com",
]

# Canonical requirement field names: single source of truth is requirements_agent/config.py.
from requirements_agent.config import CANONICAL_FIELDS, FORBIDDEN_CONSTRAINT_FIELDS  # noqa: E402,F401

# Discovery
DISCOVERY_NUM_RESULTS = 8          # per provider per query
DISCOVERY_SHORTLIST_SIZE = 8
DISCOVERY_RECENCY_DAYS = 548       # ~18 months
DISCOVERY_MAX_POOL = 30            # hits shown to the shortlisting LLM
SHORTLIST_SNIPPET_CHARS = 300      # snippet length in the shortlist prompt (~3k prompt tokens total)
SNIPPET_CHARS = 600
