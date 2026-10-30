"""
All the knobs of the pipeline live in this one file.

If you want to change HOW leads are scored (the rubric) or WHICH LLM is used,
this is the only file you need to edit. Everything else just reads from here.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
# This file is at  <project>/dags/lead_qualifier/settings.py
# so the project root is two folders up.
PROJECT_DIR = Path(os.getenv("LEAD_PROJECT_DIR", Path(__file__).resolve().parents[2]))
DATA_DIR = PROJECT_DIR / "data"       # input CSV files
OUTPUT_DIR = PROJECT_DIR / "output"   # reports are written here

DEFAULT_INPUT_FILE = "leads_full_scale_100.csv"

# The sample data is from January 2024. If we measured "how recent" against
# today's date, every lead would look stale. So we pretend today is the day
# after the newest lead in the data. Set to None to use the real current date.
DEFAULT_REFERENCE_DATE = "2024-01-21"

# ---------------------------------------------------------------------------
# Who we are (used to keep outreach messages "on brand")
# ---------------------------------------------------------------------------
OUR_COMPANY = "LeadFlow"
OUR_PRODUCT_PITCH = (
    "LeadFlow helps B2B sales teams automatically qualify and route inbound "
    "leads, so reps spend their time only on buyers who are ready to talk."
)
SENDER_NAME = "Sam"

# ---------------------------------------------------------------------------
# THE RUBRIC  (4 factors, 10 points in total)
# ---------------------------------------------------------------------------
# Factor 1 - Company size (max 3 points). We sell to mid-market companies.
#   Each entry: (smallest size, largest size, points, issue label or None)
SIZE_BANDS = [
    (1, 10, 0, "Company too small (1-10 employees)"),
    (11, 49, 1, "Small company (11-49): limited budget"),
    (50, 99, 2, None),
    (100, 2000, 3, None),                      # sweet spot: mid-market
    (2001, 5000, 2, None),
    (5001, 10**9, 1, "Large enterprise (5000+): long sales cycle"),
]
SIZE_MAX_POINTS = 3
# Companies above this size are handed to a human (enterprise team) no matter the score.
ENTERPRISE_REVIEW_THRESHOLD = 10000

# Factor 2 - Industry fit (max 2 points). Compared in lowercase.
CORE_INDUSTRIES = {
    "saas", "software", "enterprise software", "technology", "fintech",
    "cybersecurity", "ai/ml", "analytics", "healthtech", "edtech",
    "insurtech", "hr tech", "marketing",
}
ADJACENT_INDUSTRIES = {
    "finance", "healthcare", "retail", "logistics", "supply chain",
    "insurance", "manufacturing", "telecom", "consulting", "business services",
    "media", "real estate", "education", "energy", "pharmaceuticals",
    "legal", "climate tech", "e-commerce", "biotech", "services",
}
INDUSTRY_MAX_POINTS = 2

# Factor 3 - Engagement / buying intent from the lead source (max 3 points).
SOURCE_POINTS = {
    "inbound demo request": 3,   # they asked us for a demo = strongest signal
    "referral": 3,               # warm introduction
    "sales call": 2,
    "webinar attendee": 2,
    "content download": 1,
    "linkedin outreach": 1,      # we reached out to them = weakest signal
}
UNRECOGNISED_SOURCE_POINTS = 1
SOURCE_MAX_POINTS = 3

# Factor 4 - Recency of last interaction (max 2 points).
#   Each entry: (max days ago, points)
RECENCY_BANDS = [
    (14, 2),     # within 2 weeks
    (45, 1),     # within ~6 weeks
]
RECENCY_MAX_POINTS = 2
STALE_AFTER_DAYS = 90

# Decision thresholds (score is 1-10)
QUALIFIED_MIN_SCORE = 8        # 8-10  -> qualified
REVIEW_MIN_SCORE = 7           # 7     -> human review ("too close to call": 1 point short)
                               # 1-6   -> rejected
HIGH_PRIORITY_MIN_SCORE = 9    # qualified leads scoring 9-10 are HIGH priority
MAX_MISSING_FIELDS = 1         # 2+ missing rubric fields -> human review

# ---------------------------------------------------------------------------
# LLM settings (any OpenAI-compatible API: Groq, OpenAI, Gemini, ...)
# ---------------------------------------------------------------------------
# Values come from environment variables so API keys are never in the code.
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")

LLM_BATCH_SIZE = 10                 # leads per API call (we never call once per lead)
LLM_MAX_RETRIES = 4                 # attempts per batch before giving up
LLM_TIMEOUT_SECONDS = 60
LLM_PAUSE_BETWEEN_BATCHES = 1.0     # seconds; helps stay under free-tier rate limits
