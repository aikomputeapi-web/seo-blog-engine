"""Engine configuration: paths, LLM, crawler behavior."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESEARCH = DATA / "research"
STATE = DATA / "state"
LOGS = ROOT / "logs"
SITES = DATA / "sites.json"

for d in (DATA, RESEARCH, STATE, LOGS):
    d.mkdir(parents=True, exist_ok=True)

# --- LLM (zen router: free, OpenAI-compatible, no key needed) ---
LLM_URL = os.environ.get("BLOGENGINE_LLM_URL", "https://zen.nowrouter.store/v1/chat/completions")
LLM_MODEL = os.environ.get("BLOGENGINE_MODEL", "gemini-2.5-flash")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")  # optional direct-Gemini fallback, unused by default

# --- Crawler ---
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 20          # seconds per request
MAX_SITEMAP_URLS = 60      # cap URLs pulled per sitemap
MAX_ARTICLES_PER_SCRAPE = 12
MAX_COMPETITORS = 6        # competitors tracked per site
MAX_CANDIDATES_EVAL = 12   # web-search candidates evaluated per discovery

# --- Writing ---
MAX_ARTICLES_PER_RUN = 2   # avoid hammering free LLM quota
RESEARCHDEX_LIMIT = 5      # competitor article summaries attached to the writer prompt

# --- Publishing ---
ENGINE_REPO = os.environ.get("BLOGENGINE_REPO", "aikomputeapi-web/seo-blog-engine")
