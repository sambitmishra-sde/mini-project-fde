"""
Steps 3 and 4 - the parts where the LLM adds judgment.

  Step 3  write_outreach_messages : a personalised first email for each QUALIFIED lead
  Step 4  get_second_opinions     : a short AI opinion for each REVIEW lead, to help
                                    the human reviewer (the human still decides)

Both send leads in batches (settings.LLM_BATCH_SIZE per API call), never one call
per lead. If the LLM fails or returns something unusable, we fall back to safe
defaults so the pipeline always finishes.
"""

import json
import logging
import time

from . import settings
from .llm_client import LLMError, chat_json, in_batches, is_configured

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message "variants" - we pick the tone in code, based on how the lead found us
# ---------------------------------------------------------------------------
VARIANT_INSTRUCTIONS = {
    "demo_follow_up": "They asked for a demo or spoke with sales. Be direct: thank them and propose two concrete time slots for a 20-minute call.",
    "warm_referral": "They came through a referral. Be warm and mention that someone in their network suggested we connect (do NOT invent a name).",
    "value_first": "They are early-stage (content, webinar or LinkedIn). Lead with one useful idea for their industry and ask a soft question; no hard sell.",
}


def pick_variant(lead):
    source = (lead.get("source") or "").lower()
    if source in ("inbound demo request", "sales call"):
        return "demo_follow_up"
    if source == "referral":
        return "warm_referral"
    return "value_first"


def describe_lead(lead):
    """The lead facts we share with the LLM (only what it needs)."""
    return {
        "lead_id": lead["lead_id"],
        "first_name": lead["first_name"],
        "company": lead["company"],
        "company_size": lead["company_size"],
        "industry": lead["industry"],
        "source": lead["source"],
        "days_since_last_interaction": lead["days_since_last_interaction"],
    }


# ---------------------------------------------------------------------------
# Step 3: outreach messages
# ---------------------------------------------------------------------------
OUTREACH_SYSTEM_PROMPT = f"""You are {settings.SENDER_NAME}, a sales rep at {settings.OUR_COMPANY}.
{settings.OUR_PRODUCT_PITCH}

Write a short first outreach email for each lead you are given.
Rules:
- 50 to 90 words, friendly and professional, no subject line.
- Greet the person by first name (use "Hi there" if first_name is null).
- Mention the company name AND at least one specific detail (industry, team size or how they found us).
- Follow the tone in the lead's "variant_instructions".
- Never invent facts: no made-up statistics, customer names or referrer names.
- End with one clear question or call to action, then sign off as "{settings.SENDER_NAME}, {settings.OUR_COMPANY}".

Reply with JSON only, in exactly this shape:
{{"results": [{{"lead_id": "<id>", "message": "<email text>"}}]}}"""


def build_outreach_prompt(batch):
    leads = []
    for lead in batch:
        info = describe_lead(lead)
        info["variant_instructions"] = VARIANT_INSTRUCTIONS[pick_variant(lead)]
        leads.append(info)
    return "Write one email per lead:\n" + json.dumps(leads, indent=2)


def template_message(lead):
    """Fallback email used when the LLM is unavailable. Still uses the lead's details."""
    hello = f"Hi {lead['first_name']}," if lead["first_name"] else "Hi there,"
    company = lead["company"]
    industry = lead["industry"] or "your industry"
    size = f"a {lead['company_size']}-person team" if lead["company_size"] else "a growing team"
    sign_off = f"\n\nBest,\n{settings.SENDER_NAME}, {settings.OUR_COMPANY}"
    variant = pick_variant(lead)

    if variant == "demo_follow_up":
        body = (f"thanks for your interest in {settings.OUR_COMPANY}. For {size} like {company}, "
                f"the quickest win is usually automating lead qualification so reps only chase ready buyers. "
                f"Would Tuesday or Thursday work for a 20-minute walkthrough tailored to {industry}?")
    elif variant == "warm_referral":
        body = (f"someone in your network suggested I reach out. We help {industry} companies like {company} "
                f"qualify inbound leads automatically, which tends to matter a lot for {size}. "
                f"Would you be open to a quick 15-minute chat next week?")
    else:
        body = (f"thanks for engaging with our content. Many {industry} teams tell us manual lead triage "
                f"eats hours every week. Curious - how does {company} decide today which leads your "
                f"team follows up on first?")
    return f"{hello}\n\n{body[0].upper()}{body[1:]}{sign_off}"


def is_usable_message(text, lead):
    """Basic quality check on what the LLM wrote."""
    if not isinstance(text, str) or not (80 <= len(text) <= 1200):
        return False
    return (lead["company"] or "").lower() in text.lower()  # must be personalised


def write_outreach_messages(scored_leads):
    """Return {lead_id: {"message", "variant", "written_by"}} for every qualified lead."""
    qualified = [lead for lead in scored_leads if lead["decision"] == "qualified"]
    log.info("Writing outreach for %d qualified leads", len(qualified))
    if not is_configured():
        log.warning("NVIDIA_API_KEY not set - using template messages for all leads")

    messages = {}
    for batch_number, batch in enumerate(in_batches(qualified, settings.LLM_BATCH_SIZE), start=1):
        llm_results = {}
        if is_configured():
            try:
                reply = chat_json(OUTREACH_SYSTEM_PROMPT, build_outreach_prompt(batch))
                llm_results = {str(r.get("lead_id")): r for r in reply.get("results", []) if isinstance(r, dict)}
                log.info("Batch %d: LLM returned %d/%d messages", batch_number, len(llm_results), len(batch))
            except (LLMError, AttributeError) as error:
                log.error("Batch %d: LLM failed (%s) - using templates for this batch", batch_number, error)
            time.sleep(settings.LLM_PAUSE_BETWEEN_BATCHES)

        for lead in batch:
            text = (llm_results.get(lead["lead_id"]) or {}).get("message")
            if is_usable_message(text, lead):
                messages[lead["lead_id"]] = {"message": text.strip(), "variant": pick_variant(lead), "written_by": "llm"}
            else:
                if is_configured():
                    log.warning("Lead %s: LLM message missing or not personalised - using template", lead["lead_id"])
                messages[lead["lead_id"]] = {"message": template_message(lead), "variant": pick_variant(lead), "written_by": "template"}
    return messages


# ---------------------------------------------------------------------------
# Step 4: AI second opinion for leads that need human review
# ---------------------------------------------------------------------------
REVIEW_SYSTEM_PROMPT = f"""You help the sales team at {settings.OUR_COMPANY}, which sells to mid-market B2B companies.
{settings.OUR_PRODUCT_PITCH}

Each lead below could not be decided automatically. For each one give a recommendation
("lean_qualify", "lean_reject" or "need_more_info") and ONE sentence explaining why,
based only on the facts given. Missing values are null - treat them as unknown, do not guess them.

Reply with JSON only, in exactly this shape:
{{"results": [{{"lead_id": "<id>", "recommendation": "<value>", "reason": "<one sentence>"}}]}}"""

VALID_RECOMMENDATIONS = {"lean_qualify", "lean_reject", "need_more_info"}


def build_review_prompt(batch):
    leads = []
    for lead in batch:
        info = describe_lead(lead)
        info["rubric_score"] = lead["score"]
        info["why_flagged"] = lead["decision_reason"]
        leads.append(info)
    return "Leads needing review:\n" + json.dumps(leads, indent=2)


def get_second_opinions(scored_leads):
    """Return {lead_id: {"recommendation", "reason", "written_by"}} for every review lead."""
    to_review = [lead for lead in scored_leads if lead["decision"] == "review"]
    log.info("Getting AI second opinions for %d review leads", len(to_review))
    unavailable = {"recommendation": "not_available", "reason": "AI opinion unavailable - review manually", "written_by": "none"}

    opinions = {}
    for batch_number, batch in enumerate(in_batches(to_review, settings.LLM_BATCH_SIZE), start=1):
        llm_results = {}
        if is_configured():
            try:
                reply = chat_json(REVIEW_SYSTEM_PROMPT, build_review_prompt(batch))
                llm_results = {str(r.get("lead_id")): r for r in reply.get("results", []) if isinstance(r, dict)}
            except (LLMError, AttributeError) as error:
                log.error("Review batch %d: LLM failed (%s)", batch_number, error)
            time.sleep(settings.LLM_PAUSE_BETWEEN_BATCHES)

        for lead in batch:
            result = llm_results.get(lead["lead_id"]) or {}
            if result.get("recommendation") in VALID_RECOMMENDATIONS and result.get("reason"):
                opinions[lead["lead_id"]] = {"recommendation": result["recommendation"],
                                             "reason": str(result["reason"]).strip(), "written_by": "llm"}
            else:
                opinions[lead["lead_id"]] = dict(unavailable)
    return opinions
