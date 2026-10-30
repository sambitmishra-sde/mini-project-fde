"""
Airflow DAG: Lead Qualification Pipeline
========================================

New to Airflow? Quick glossary:
  * DAG   - "Directed Acyclic Graph": a workflow made of steps (tasks) with arrows
            between them. This file defines ONE DAG.
  * Task  - one step. Here every function decorated with @task becomes a task.
  * XCom  - how tasks pass data to each other. When a @task function RETURNS a
            value, Airflow saves it, and you can give it to the next task as an
            argument. (Keep XCom data small and JSON-friendly - ours is ~100 leads.)
  * Params- inputs you can type in when you click "Trigger DAG" in the UI.

The workflow looks like this in the Airflow "Graph" view:

                                    +--> write_outreach_messages --+
    load_leads --> score_leads -----+                              +--> build_report
                                    +--> get_second_opinions ------+

The two AI tasks don't depend on each other, so Airflow runs them in parallel.

All the real logic lives in the `lead_qualifier` package next to this file.
This file only says WHAT runs and in WHICH ORDER - that is the job of a DAG.
"""

from datetime import datetime, timedelta

# Airflow 3 moved the DAG-authoring API to `airflow.sdk`. Fall back to the
# Airflow 2 location so this file works on both versions.
try:
    from airflow.sdk import dag, task
except ImportError:
    from airflow.decorators import dag, task

from lead_qualifier import ai_steps, data_loader, report, rubric, settings

# Settings applied to every task in the DAG
default_args = {
    "owner": "sales-ops",
    "retries": 1,                        # if a task crashes, Airflow tries once more...
    "retry_delay": timedelta(minutes=1), # ...after waiting 1 minute
}


@dag(
    dag_id="lead_qualification",
    description="Score leads with a rubric, write outreach with an LLM, produce a report",
    schedule=None,                 # no timetable: run it by clicking "Trigger" (set e.g. "@daily" later)
    start_date=datetime(2024, 1, 1),
    catchup=False,                 # don't try to "back-fill" runs for past dates
    default_args=default_args,
    tags=["leads", "llm", "beginner"],
    params={
        # Shown in the "Trigger DAG" form. File names are looked up in the data/ folder.
        "input_file": settings.DEFAULT_INPUT_FILE,
        "reference_date": settings.DEFAULT_REFERENCE_DATE,  # "YYYY-MM-DD" used as "today"
    },
)
def lead_qualification():

    @task
    def load_leads(**context):
        """Task 1: read the CSV and clean every row."""
        input_file = context["params"]["input_file"]
        return data_loader.load_leads(input_file)

    @task
    def score_leads(leads, **context):
        """Task 2: apply the rubric -> score, decision and priority for every lead."""
        reference_date = context["params"]["reference_date"] or None
        return rubric.score_leads(leads, reference_date)

    @task
    def write_outreach_messages(scored_leads):
        """Task 3: LLM writes a first email for each qualified lead (in batches)."""
        return ai_steps.write_outreach_messages(scored_leads)

    @task
    def get_second_opinions(scored_leads):
        """Task 4: LLM gives a second opinion on leads flagged for human review."""
        return ai_steps.get_second_opinions(scored_leads)

    @task
    def build_report(scored_leads, messages, opinions, **context):
        """Task 5: write output/<input>_report.json and output/<input>_leads.csv."""
        params = context["params"]
        return report.build_report(scored_leads, messages, opinions,
                                   params["input_file"], params["reference_date"])

    # ---- Wire the tasks together --------------------------------------------
    # Passing one task's result into another task creates the arrow between them.
    leads = load_leads()
    scored = score_leads(leads)
    messages = write_outreach_messages(scored)
    opinions = get_second_opinions(scored)
    build_report(scored, messages, opinions)


# Calling the decorated function creates the DAG object Airflow looks for.
lead_qualification()
