"""Settings loaded from .env plus tunable constants.

Reads <this folder>/.env first, then the repo-root .env (first value wins), so one
root .env can serve every agent folder.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env")
if str(REPO_ROOT) not in sys.path:  # so `requirements_agent.config` is importable
    sys.path.append(str(REPO_ROOT))

TELEM_API_KEY = os.getenv("TELEM_API_KEY")
TELEM_BASE_URL = os.getenv("TELEM_BASE_URL", "https://router.telem.ai")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Cheapest current Claude model; these are short JSON extraction / classification calls.
LLM_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-haiku-5-5"
LLM_EFFORT = os.getenv("ANTHROPIC_EFFORT", "low")             # low | medium | high
LLM_THINKING = os.getenv("ANTHROPIC_THINKING", "off").lower()  # off | adaptive
LLM_MIN_MAX_TOKENS = 4096                                       # ceiling only; unused tokens aren't billed
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
DISCOVERY_SHORTLIST_SIZE = 10
DISCOVERY_RECENCY_DAYS = 548       # ~18 months
DISCOVERY_MAX_POOL = 30            # hits shown to the shortlisting LLM
SHORTLIST_SNIPPET_CHARS = 300      # snippet length in the shortlist prompt (~3k prompt tokens total)
SNIPPET_CHARS = 600

# Catalog reader
FETCH_BATCH = 5
FETCH_MAX_CHARS = 15000            # per page, sent to Telem as inline_max_chars and to the LLM
MIN_PAGE_CHARS = 500               # below this a fetch is treated as failed -> Tavily fallback
CATALOG_WORKERS = 4                # parallel LLM extractions
# Fixed demo FX rates (shown in the report); update if needed.
FX_TO_USD = {"USD": 1.0, "$": 1.0, "US$": 1.0, "EUR": 1.08, "€": 1.08, "GBP": 1.27, "£": 1.27,
             "CNY": 0.14, "RMB": 0.14, "¥": 0.14, "JPY": 0.0067, "CAD": 0.73, "AUD": 0.66, "INR": 0.012}

# Verifier
VERIFY_MAX_CLAIMS = 4              # claims checked per candidate
VERIFY_CONCURRENCY = 4             # candidates verified in parallel
VERIFY_NUM_RESULTS = 5             # per provider per query
VERIFY_MAX_ROUTING_PROVIDERS = 3
VERIFY_MAX_EVIDENCE = 32           # evidence items shown to the judge per candidate
VERIFY_BACKGROUND_SLOTS = 6        # of those, reserved for vendor-background items and for deployment items (each)
VERIFY_SELF_REPORTED = 2           # seller's own about/contact pages shown to the judge (labelled, vendor facts only)
VERIFY_YOUNG_DOMAIN_YEARS = 1.0    # seller domain younger than this -> code risk signal
VERIFY_DOMAIN_AGE = True           # RDAP lookup of the seller domain
EVIDENCE_CHARS = 400
FREE_MAIL_DOMAINS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "qq.com", "163.com", "126.com",
                     "aliyun.com", "foxmail.com", "sina.com"}
# Scoring weights (spec 4.3)
W_FIT, W_VERIFY, W_TRUST = 0.5, 0.3, 0.2
