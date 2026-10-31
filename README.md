# Lead Intelligence System

Our sales team gets around 1,200 leads a month and spends 8–12 minutes deciding on each one. This tool does that first pass for them. It reads a list of leads, scores each one, writes a personal first email for the good ones, and hands back a ranked list the team can start calling straight away.

It runs as a small Airflow workflow, and you can also run it as a plain Python script.

## How to run it

You only need Python 3.9 or newer. The script itself needs nothing extra installed.

1. **Get a free NVIDIA API key** at [build.nvidia.com](https://build.nvidia.com). The key starts with `nvapi-`. Then set it in your terminal:
   ```bash
   export NVIDIA_API_KEY="nvapi-..."
   ```
2. **Run it** from the project folder:
   ```bash
   python run_local.py                                   # all 100 leads
   python run_local.py --input leads_testing.csv         # the messy test file
   python run_local.py --input leads_training.csv --limit 5   # quick 5-lead check
   ```
3. **Open the results** in the `output/` folder:
   - `..._leads.csv` opens in Excel or Google Sheets. It has one row per lead, with the decision, the reasons and the email.
   - `..._report.json` has the full report: totals, the priority queue, leads for review, and sample emails.

No key? The tool still works. It writes the emails from templates instead of the AI.

To run it inside Airflow, follow **[HOW_TO_RUN.md](HOW_TO_RUN.md)**. It covers Docker, a local Airflow install and troubleshooting.

## How leads are scored

Each lead gets up to 10 points, split across four things:
- **Company size** (3 points). Companies of 100–2,000 people score highest.
- **Industry** (2 points). Software and tech score highest.
- **How they found us** (3 points). A demo request or a referral scores highest, cold LinkedIn outreach lowest.
- **How recently we spoke** (2 points). Contact within the last two weeks scores highest.

Leads scoring **8 or more are qualified** and ranked for outreach. A score of **7 goes to a person to decide**, and **6 or less is rejected**. The scoring uses fixed rules rather than AI, so the same lead always gets the same score, with a reason for every point. The AI writes the emails and gives a quick opinion on borderline leads, but a person still makes those calls.

On the 100-lead sample, the tool qualified 35 leads, sent 23 to review and rejected 42.

## Known limitations and edge cases

- **Missing details:** a lead with missing details (size, industry or source) is never rejected for that alone. If it could still qualify, it goes to a person to check. Leads with no company name, a future contact date, or more than 10,000 employees are always sent to a person.
- **AI failures:** if the AI is slow, rate-limited or gives a bad answer, the tool retries a few times. It then falls back to a template email, so a run never stops halfway.
- **"Today" is fixed:** the sample data is from January 2024, so "how recent" is measured from 21 Jan 2024. Use `--reference-date` to change it.
- **Fixed industry list:** industries we haven't listed, such as "Hospitality", get 0 points until someone adds them in `dags/lead_qualifier/settings.py`.
- **Sample reports:** the reports in `output/` were made without an API key, so their emails are templates.
- **Not handled:** the tool doesn't detect duplicate leads or connect to a CRM. It's built for hundreds of leads per run, not tens of thousands.
