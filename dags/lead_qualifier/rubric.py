"""
Step 2 - Score every lead with a simple, explainable rubric.

This part is deliberately NOT done by the LLM: plain rules give the same answer
every time, and every point can be explained to the sales team.

    Factor            Max points
    ----------------  ----------
    Company size          3
    Industry fit          2
    Engagement source     3
    Recency               2
                         ---
    Total                10

Decision:  8-10 qualified | 7 review (human decides) | 1-6 rejected
Missing data never causes a rejection on its own: if the lead COULD reach 8
once the missing field is known, it goes to human review instead.
(the exact points and thresholds live in settings.py)
"""

import logging
from datetime import date

from . import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# One small function per factor.
# Each returns: (points, max_points, explanation, issue_label_or_None, is_missing)
# ---------------------------------------------------------------------------

def score_company_size(size):
    if size is None:
        return 0, settings.SIZE_MAX_POINTS, "Company size unknown (0 pts)", None, True
    for low, high, points, issue in settings.SIZE_BANDS:
        if low <= size <= high:
            text = f"Company size {size} -> {points}/{settings.SIZE_MAX_POINTS} pts"
            return points, settings.SIZE_MAX_POINTS, text, issue, False
    return 0, settings.SIZE_MAX_POINTS, f"Company size {size} out of range (0 pts)", None, False


def score_industry(industry):
    if industry is None:
        return 0, settings.INDUSTRY_MAX_POINTS, "Industry unknown (0 pts)", None, True
    key = industry.lower()
    if key in settings.CORE_INDUSTRIES:
        return 2, 2, f"{industry} is a core target industry (2/2 pts)", None, False
    if key in settings.ADJACENT_INDUSTRIES:
        return 1, 2, f"{industry} is an adjacent industry (1/2 pts)", None, False
    return 0, 2, f"{industry} is outside our target industries (0/2 pts)", "Industry outside target market", False


def score_source(source):
    if source is None:
        return 0, settings.SOURCE_MAX_POINTS, "Lead source unknown (0 pts)", None, True
    points = settings.SOURCE_POINTS.get(source.lower(), settings.UNRECOGNISED_SOURCE_POINTS)
    issue = "Weak engagement signal (cold source)" if points <= 1 else None
    text = f"Source '{source}' -> {points}/{settings.SOURCE_MAX_POINTS} pts"
    return points, settings.SOURCE_MAX_POINTS, text, issue, False


def score_recency(days_ago):
    if days_ago is None:
        return 0, settings.RECENCY_MAX_POINTS, "Last interaction date unknown (0 pts)", None, True
    for max_days, points in settings.RECENCY_BANDS:
        if days_ago <= max_days:
            return points, settings.RECENCY_MAX_POINTS, f"Last contact {days_ago} days ago ({points}/2 pts)", None, False
    if days_ago > settings.STALE_AFTER_DAYS:
        return 0, 2, f"Last contact {days_ago} days ago - stale (0/2 pts)", f"Stale lead (no contact in {settings.STALE_AFTER_DAYS}+ days)", False
    return 0, 2, f"Last contact {days_ago} days ago (0/2 pts)", "Interaction cooling off (45+ days)", False


# ---------------------------------------------------------------------------
# Put the factors together for one lead
# ---------------------------------------------------------------------------

def days_since(iso_date, reference_date):
    if iso_date is None:
        return None
    return (reference_date - date.fromisoformat(iso_date)).days


def score_one_lead(lead, reference_date):
    lead = dict(lead)  # copy - never modify the input of a previous task
    days_ago = days_since(lead["last_interaction_date"], reference_date)
    lead["days_since_last_interaction"] = days_ago

    future_date = days_ago is not None and days_ago < 0
    if future_date:
        lead["data_issues"] = lead["data_issues"] + ["last_interaction_date is in the future"]
        days_ago = None  # don't give points for an impossible date

    factors = {
        "company_size": score_company_size(lead["company_size"]),
        "industry": score_industry(lead["industry"]),
        "source": score_source(lead["source"]),
        "recency": score_recency(days_ago),
    }

    total = sum(f[0] for f in factors.values())
    missing = [name for name, f in factors.items() if f[4]]
    # Best case: what the score could be if every missing field were perfect
    best_case = total + sum(factors[name][1] for name in missing)

    lead["score"] = max(1, total)  # brief asks for a 1-10 scale
    lead["score_breakdown"] = {name: f[0] for name, f in factors.items()}
    lead["reasoning"] = [f[2] for f in factors.values()]
    lead["weaknesses"] = [f[3] for f in factors.values() if f[3]]
    lead["missing_fields"] = missing

    decision, category, why = decide(lead, total, best_case, missing, future_date)
    lead["decision"] = decision
    lead["decision_category"] = category   # short label, used for stats in the report
    lead["decision_reason"] = why           # full sentence for humans
    return lead


def decide(lead, total, best_case, missing, future_date):
    """Turn the score into qualified / review / rejected. Rules are checked top to bottom.

    Returns (decision, short category, human-readable reason).
    """
    if len(missing) > settings.MAX_MISSING_FIELDS:
        return ("review", "Too much missing data",
                f"Too much missing data ({', '.join(missing)}) to decide automatically")
    if lead["company"] is None:
        return ("review", "Missing company name",
                "Company name missing - cannot research or personalise outreach")
    if future_date:
        return ("review", "Interaction date in the future",
                "Interaction date is in the future - please check the CRM record")
    if lead["company_size"] and lead["company_size"] > settings.ENTERPRISE_REVIEW_THRESHOLD:
        return ("review", "Very large enterprise",
                f"Very large company ({lead['company_size']} employees) - route to enterprise team")

    if total >= settings.QUALIFIED_MIN_SCORE:
        return ("qualified", "Meets qualification bar",
                f"Score {total}/10 meets the qualification bar ({settings.QUALIFIED_MIN_SCORE}+)")
    if missing and best_case >= settings.QUALIFIED_MIN_SCORE:
        # Don't reject someone just because we lack data that could have qualified them
        return ("review", "Could qualify once missing data is known",
                f"Score {total}/10, but could reach {best_case} once '{missing[0]}' is known")
    if total >= settings.REVIEW_MIN_SCORE:
        return ("review", "Borderline score",
                f"Score {total}/10 is borderline - too close to call")
    return ("rejected", "Below review bar",
            f"Score {total}/10 is below the review bar ({settings.REVIEW_MIN_SCORE})")


def assign_priority(scored_leads):
    """Rank qualified leads: best score first, then most recent contact."""
    qualified = [lead for lead in scored_leads if lead["decision"] == "qualified"]
    qualified.sort(key=lambda l: (-l["score"], l["days_since_last_interaction"] or 0, -l["score_breakdown"]["source"]))
    rank_by_id = {lead["lead_id"]: rank for rank, lead in enumerate(qualified, start=1)}

    for lead in scored_leads:
        lead["priority_rank"] = rank_by_id.get(lead["lead_id"])
        if lead["decision"] == "qualified":
            lead["priority"] = "HIGH" if lead["score"] >= settings.HIGH_PRIORITY_MIN_SCORE else "MEDIUM"
        elif lead["decision"] == "review":
            lead["priority"] = "HUMAN_REVIEW"
        else:
            lead["priority"] = "NONE"
    return scored_leads


def score_leads(leads, reference_date=None):
    """Score every lead. `reference_date` is 'YYYY-MM-DD' or None for today."""
    ref = date.fromisoformat(reference_date) if reference_date else date.today()
    log.info("Scoring %d leads (reference date %s)", len(leads), ref)

    scored = [score_one_lead(lead, ref) for lead in leads]
    scored = assign_priority(scored)

    counts = {d: sum(1 for l in scored if l["decision"] == d) for d in ("qualified", "review", "rejected")}
    log.info("Decisions: %s", counts)
    return scored
