"""
Lead qualifier - plain Python building blocks used by the Airflow DAG.

Nothing in this package imports Airflow, so every step can also be run and
tested on its own (see run_local.py in the project root).

Pipeline:  data_loader -> rubric -> ai_steps (messages + second opinions) -> report
"""
