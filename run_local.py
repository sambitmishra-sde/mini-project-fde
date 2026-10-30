"""
Run the same pipeline WITHOUT Airflow - handy for learning, testing prompts and debugging.

    python run_local.py                                  # 100-lead dataset
    python run_local.py --input leads_testing.csv        # messy edge cases
    python run_local.py --input leads_training.csv --limit 5   # try prompts on 5 leads

It calls exactly the same functions, in the same order, as the Airflow DAG.
"""

import argparse
import logging
import sys
from pathlib import Path

# Make the `lead_qualifier` package (inside dags/) importable, just like Airflow does.
sys.path.insert(0, str(Path(__file__).resolve().parent / "dags"))

from lead_qualifier import ai_steps, data_loader, report, rubric, settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Qualify leads from a CSV file.")
    parser.add_argument("--input", default=settings.DEFAULT_INPUT_FILE,
                        help="CSV file name in data/ or a full path (default: %(default)s)")
    parser.add_argument("--reference-date", default=settings.DEFAULT_REFERENCE_DATE,
                        help="Date treated as 'today' for recency, YYYY-MM-DD (default: %(default)s)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N leads (useful for testing prompts)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    leads = data_loader.load_leads(args.input)                      # Task 1
    if args.limit:
        leads = leads[:args.limit]
    scored = rubric.score_leads(leads, args.reference_date)         # Task 2
    messages = ai_steps.write_outreach_messages(scored)             # Task 3
    opinions = ai_steps.get_second_opinions(scored)                 # Task 4
    report_path = report.build_report(scored, messages, opinions,   # Task 5
                                      args.input, args.reference_date)
    print(f"\nDone. Report: {report_path}")


if __name__ == "__main__":
    main()
