# Lead Intelligence System (Airflow)

Auto-qualifies sales leads from a CSV, writes personalised first emails with an LLM, and produces a report the sales team can act on. It's built as one beginner-friendly **Apache Airflow DAG**.

```
                                 ┌─> write_outreach_messages ─┐   (LLM, batched)
load_leads ─> score_leads ───────┤                            ├─> build_report
 (clean CSV)  (rubric, no LLM)   └─> get_second_opinions ─────┘   (JSON + CSV)
```

| File | What it does |
|---|---|
| `dags/lead_qualification_dag.py` | **The only Airflow file.** Defines the 5 tasks and their order |
| `dags/lead_qualifier/settings.py` | Rubric points, thresholds and LLM settings. **Edit this to tune.** |
| `dags/lead_qualifier/data_loader.py` → `rubric.py` → `ai_steps.py` → `report.py` | One file per step. Plain Python, no Airflow imports |
| `dags/lead_qualifier/llm_client.py` | Batched calls to any OpenAI-compatible API, with retries |
| `run_local.py` | Runs the same pipeline without Airflow (the CLI tool) |
| `data/` · `output/` | Input CSVs · generated reports (sample runs are included) |

## How to run

**1. Without Airflow (quickest, needs only Python 3.9+):**
```bash
export LLM_API_KEY=your_groq_key        # optional: without it, template messages are used
python run_local.py                                   # 100 leads
python run_local.py --input leads_testing.csv         # messy edge cases
python run_local.py --input leads_training.csv --limit 5   # test prompts on 5 leads
```
**2. In Airflow with Docker:** `cp .env.example .env`, add your key, run `docker compose up`, then open http://localhost:8080. Find the DAG **lead_qualification**, click **Trigger** (you can change `input_file` there), and open the **Graph** view to watch each task. Click a task and choose **Logs** to see what it did.

**3. In Airflow without Docker:** `pip install -r requirements.txt` (use the constraints command in that file), then `export AIRFLOW_HOME=$PWD/airflow_home AIRFLOW__CORE__DAGS_FOLDER=$PWD/dags AIRFLOW__CORE__LOAD_EXAMPLES=False` and `airflow standalone`.

The default LLM is Groq's free tier (`llama-3.1-8b-instant`). For OpenAI or Gemini, see `.env.example`.

## Qualification rubric

Each lead gets up to 10 points: **company size** (3, best at 100–2000 employees), **industry fit** (2 for core tech, 1 for adjacent), **engagement source** (3 for demo request or referral down to 1 for content download or LinkedIn), and **recency** (2 if contacted within 14 days, 1 within 45). A score of **8–10 is qualified** (9+ is HIGH priority), **7 goes to human review**, and **≤6 is rejected**. Scoring is done by deterministic rules, so it's consistent and every point is explained. The LLM is used for judgment: it writes personalised emails in 3 tones chosen by lead source (demo follow-up, warm referral, value-first), and gives a second opinion on review leads. A human still makes the final call on those.

**Human-in-the-loop rules.** Some leads go to review instead of being auto-decided:
- 2+ rubric fields are missing.
- The company name is missing.
- The interaction date is in the future.
- The company has more than 10,000 employees (routed to the enterprise team).
- A lead is never rejected for missing data alone. If it *could* score 8 once the missing field is known, it goes to review.

**Results (100 leads):** 35 qualified (13 HIGH), 23 review, 42 rejected. The top rejection reasons are cold sources and industries outside our target market. See `output/leads_full_scale_100_report.json`.

## Report contents

`output/<input>_report.json` contains:
- `summary`: totals, percentages, common rejection reasons and data-quality issues
- `priority_queue`: ranked leads, each with its reasoning and email
- `flagged_for_review`: each lead with an AI second opinion
- `disqualified`
- `sample_outreach_messages`: 3–5 emails, covering every variant
- `all_leads`

`output/<input>_leads.csv` has the same results in a format you can open in a spreadsheet.

## Robustness

- **API failures:** rate limits (429, honouring `Retry-After`), 5xx errors, timeouts and invalid JSON are retried with exponential backoff, up to 4 attempts per batch. If a batch still fails, or the LLM leaves out a lead or writes a message that doesn't name the company, only those leads fall back to a personalised template. The run never crashes, and `outreach_messages_written_by` shows how many emails came from the LLM vs. the template. On top of this, Airflow retries a crashed task once.
- **Messy data:** `NA`, `Unknown` and blank values all count as missing, and invalid numbers or dates are logged in `data_issues` per lead. A missing input file or missing CSV columns *does* fail the task, on purpose, so the problem is visible.

## Known limitations

- **Recency:** measured against `reference_date` (default `2024-01-21`, because the sample data is from January 2024). Set it to empty or `None` to use today's date.
- **Industry matching:** uses fixed lists, so unlisted industries score 0 until they're added to `settings.py`.
- **Sample outputs:** the included reports were generated **without** an API key, so all emails are template-based. Run with a key to get LLM-written emails.
- **No de-duplication:** duplicate leads aren't detected, and there's no CRM integration.
- **XCom:** lead data is passed between tasks via XCom, which is fine for hundreds of leads. For tens of thousands, write to files or a database and pass paths instead.
