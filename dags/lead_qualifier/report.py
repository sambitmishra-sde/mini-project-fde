"""
Step 5 - Combine everything into a report the sales team can act on.

Writes two files into output/:
  <input>_report.json  - full report: summary stats, priority queue, review list,
                         rejected list, sample messages, and every lead's details
  <input>_leads.csv    - one row per lead, easy to open in Excel / Google Sheets
"""

import csv
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import settings
from .llm_client import is_configured

log = logging.getLogger(__name__)


def percent(part, whole):
    return round(100 * part / whole, 1) if whole else 0.0


def pick_sample_messages(priority_queue, how_many=5):
    """Pick up to 5 messages, trying to show every variant at least once."""
    samples, used_variants = [], set()
    for lead in priority_queue:                      # first pass: one per variant
        if lead["outreach"] and lead["outreach"]["variant"] not in used_variants:
            samples.append(lead)
            used_variants.add(lead["outreach"]["variant"])
    for lead in priority_queue:                      # second pass: fill up
        if len(samples) >= how_many:
            break
        if lead["outreach"] and lead not in samples:
            samples.append(lead)
    samples = samples[:how_many]
    return [{"priority_rank": l["priority_rank"], "name": l["name"], "company": l["company"],
             "variant": l["outreach"]["variant"], "written_by": l["outreach"]["written_by"],
             "message": l["outreach"]["message"]} for l in samples]


def build_report(scored_leads, messages, opinions, input_file, reference_date):
    # Attach the AI outputs to each lead
    leads = []
    for lead in scored_leads:
        lead = dict(lead)
        lead["outreach"] = messages.get(lead["lead_id"])
        lead["ai_second_opinion"] = opinions.get(lead["lead_id"])
        leads.append(lead)

    qualified = sorted([l for l in leads if l["decision"] == "qualified"], key=lambda l: l["priority_rank"])
    review = sorted([l for l in leads if l["decision"] == "review"], key=lambda l: -l["score"])
    rejected = sorted([l for l in leads if l["decision"] == "rejected"], key=lambda l: -l["score"])
    total = len(leads)

    rejection_reasons = Counter(reason for l in rejected for reason in l["weaknesses"])
    review_reasons = Counter(l["decision_category"] for l in review)
    data_issues = Counter(issue for l in leads for issue in l["data_issues"])
    written_by = Counter(m["written_by"] for m in messages.values())

    report = {
        "run_info": {
            "input_file": str(input_file),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reference_date": reference_date,
            "llm_model": settings.LLM_MODEL if is_configured() else None,
            "llm_used": is_configured(),
            "rubric": "Size (3) + Industry (2) + Source/intent (3) + Recency (2) = 10. "
                      f"Qualified >= {settings.QUALIFIED_MIN_SCORE}, "
                      f"review >= {settings.REVIEW_MIN_SCORE}, rejected below that. "
                      "Missing data -> human review instead of rejection.",
        },
        "summary": {
            "total_processed": total,
            "qualified": len(qualified),
            "qualified_pct": percent(len(qualified), total),
            "needs_review": len(review),
            "needs_review_pct": percent(len(review), total),
            "rejected": len(rejected),
            "rejected_pct": percent(len(rejected), total),
            "high_priority": sum(1 for l in qualified if l["priority"] == "HIGH"),
            "average_score": round(sum(l["score"] for l in leads) / total, 2) if total else 0,
            "common_rejection_reasons": [{"reason": r, "count": c} for r, c in rejection_reasons.most_common()],
            "review_reasons": [{"reason": r, "count": c} for r, c in review_reasons.most_common()],
            "data_quality_issues": [{"issue": i, "count": c} for i, c in data_issues.most_common()],
            "outreach_messages_written_by": dict(written_by),
        },
        "priority_queue": [
            {"priority_rank": l["priority_rank"], "priority": l["priority"], "score": l["score"],
             "name": l["name"], "company": l["company"], "industry": l["industry"],
             "company_size": l["company_size"], "source": l["source"],
             "reasoning": l["reasoning"], "outreach_message": l["outreach"]["message"]}
            for l in qualified
        ],
        "flagged_for_review": [
            {"score": l["score"], "name": l["name"], "company": l["company"],
             "why_flagged": l["decision_reason"], "data_issues": l["data_issues"],
             "reasoning": l["reasoning"], "ai_second_opinion": l["ai_second_opinion"]}
            for l in review
        ],
        "disqualified": [
            {"score": l["score"], "name": l["name"], "company": l["company"],
             "rejection_reasons": l["weaknesses"], "reasoning": l["reasoning"]}
            for l in rejected
        ],
        "sample_outreach_messages": pick_sample_messages(qualified),
        "all_leads": leads,
    }

    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(input_file).stem
    json_path = settings.OUTPUT_DIR / f"{stem}_report.json"
    csv_path = settings.OUTPUT_DIR / f"{stem}_leads.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    write_csv(leads, csv_path)

    log.info("Summary: %s", {k: v for k, v in report["summary"].items() if not isinstance(v, (list, dict))})
    log.info("Report written to %s and %s", json_path, csv_path)
    return str(json_path)


def write_csv(leads, path):
    columns = ["priority_rank", "decision", "priority", "score", "name", "company", "company_size",
               "industry", "source", "last_interaction_date", "decision_reason", "reasoning",
               "data_issues", "ai_second_opinion", "outreach_message"]
    order = {"qualified": 0, "review": 1, "rejected": 2}
    rows = sorted(leads, key=lambda l: (order[l["decision"]], l["priority_rank"] or 0, -l["score"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for l in rows:
            opinion = l["ai_second_opinion"]
            writer.writerow({
                **{c: l.get(c) for c in columns[:11]},
                "reasoning": " | ".join(l["reasoning"]),
                "data_issues": "; ".join(l["data_issues"]),
                "ai_second_opinion": f"{opinion['recommendation']}: {opinion['reason']}" if opinion else "",
                "outreach_message": l["outreach"]["message"] if l["outreach"] else "",
            })
