# How to Run the Lead Qualification App

This is the only setup guide you need. There are two ways to run the app:

- **Option A: plain Python.** Quickest.
- **Option B: Airflow DAG.** The same steps, run and monitored from the Airflow web UI.

Both options run the same code and write the same reports.

---

## Step 1: Get a free NVIDIA API key

1. Go to https://build.nvidia.com and sign in. A free NVIDIA developer account is enough.
2. Open any chat model, for example **nemotron-3.5-lightning-30b-a3b**.
3. Click **Get API Key** and copy the key. It starts with `nvapi-`.
4. Put the key in an environment variable in the terminal you'll run the app from:

   ```bash
   # macOS / Linux
   export NVIDIA_API_KEY="nvapi-xxxxxxxxxxxxxxxx"
   ```
   ```powershell
   # Windows PowerShell
   $env:NVIDIA_API_KEY = "nvapi-xxxxxxxxxxxxxxxx"
   ```

**No key?** The app still runs. Emails then come from built-in templates, which still use each lead's details, instead of the LLM.

---

## Option A: Run with plain Python

Requires **Python 3.9 or newer**. You can skip `requirements.txt` for this option. The app uses only the Python standard library, and that file only installs Airflow (needed for Option B).

Run these commands from the project folder (`mini-project-fde/`):

```bash
# 1. Try the prompts on 5 leads first (a quick, cheap check)
python run_local.py --input leads_training.csv --limit 5

# 2. Robustness check on the messy edge-case file
python run_local.py --input leads_testing.csv

# 3. The full 100-lead run (this is the default file)
python run_local.py
```

Options:

| Flag | Meaning | Default |
|---|---|---|
| `--input` | A CSV file name in `data/`, or a full path | `leads_full_scale_100.csv` |
| `--limit N` | Only process the first N leads | all leads |
| `--reference-date` | The date treated as "today" when scoring recency | `2024-01-21` |

---

## Option B: Run as an Airflow DAG

Airflow runs on macOS and Linux. On Windows, run these steps inside WSL.

### B1. Install and start Airflow (one-time setup)

You need Airflow installed before you can run the DAG. Run this from the project folder (`mini-project-fde/`):

```bash
# 1. Create an isolated Python environment (needs Python 3.10 - 3.14)
python3 -m venv .venv && source .venv/bin/activate
hash -r                       # make the shell forget any cached global `pip`
which python                  # must end in .../mini-project-fde/.venv/bin/python

# 2. Upgrade pip inside the venv (old pip crashes on Python 3.12+)
python -m pip install --upgrade pip setuptools

# 3. Install Airflow with the official constraints file for YOUR Python version
PY=$(python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
python -m pip install -r requirements.txt --constraint \
  "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-${PY}.txt"
airflow version               # should print 3.3.2
```

Then start Airflow. Run these in the **same terminal** where you set `NVIDIA_API_KEY` (Step 1). Airflow passes your terminal's environment variables on to the tasks:

```bash
export AIRFLOW_HOME="$PWD/airflow_home"                   # Airflow's own files go here
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"              # where Airflow looks for our DAG
export AIRFLOW__CORE__LOAD_EXAMPLES=False                  # hide Airflow's ~50 example DAGs
export AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True  # no login page (local use only)
airflow standalone
```

`airflow standalone` starts the whole of Airflow in one process: the web UI, the scheduler and a small database. It's meant for learning, not production. Leave this terminal open while you work. To stop Airflow, press `Ctrl+C` there. Next time, just activate the venv and repeat the `export` lines and `airflow standalone`; you don't need to reinstall.

### B2. Run the DAG from the Airflow web UI

**1. Open the UI.** Wait until the terminal stops printing startup messages (about a minute), then open **http://localhost:8080**. You go straight in, with no login, because of the `SIMPLE_AUTH_MANAGER_ALL_ADMINS` setting.

**2. Find the DAG.** Click **Dags** in the left menu. You should see **`lead_qualification`**, with the tags `leads`, `llm` and `beginner`.
- Not there yet? Airflow scans the `dags/` folder every so often. Wait 30–60 seconds and refresh.
- Still not there? A red **Dag Import Errors** banner at the top of the page shows why Airflow couldn't load the file. Click it to see the Python error.

**3. Unpause it.** New DAGs start **paused**, which means Airflow won't run them. Click the toggle switch next to `lead_qualification` so it turns on (blue). You only need to do this once.

**4. Open the DAG.** Click the name `lead_qualification`. This page shows the DAG's past runs and its tasks. Take a look at the **Graph** tab before running anything, because it shows how the 5 tasks connect:

```
load_leads ──> score_leads ──┬──> write_outreach_messages ──┬──> build_report
                             └──> get_second_opinions ──────┘
```

| Task | What it does |
|---|---|
| `load_leads` | Reads the CSV from `data/` and cleans each row (blanks, `NA`, bad dates) |
| `score_leads` | Scores each lead out of 10 and decides: qualified, review or rejected |
| `write_outreach_messages` | Asks the NVIDIA LLM to write an email for each qualified lead, 10 leads per request |
| `get_second_opinions` | Asks the LLM for a short opinion on each lead sent for human review |
| `build_report` | Writes the JSON report and the CSV file to `output/` |

The two middle tasks don't depend on each other, so Airflow runs them **at the same time**.

**5. Trigger a run.** Click the **Trigger** button (top right). A form opens with the DAG's two **parameters**:

| Parameter | What to enter | Default |
|---|---|---|
| `input_file` | A CSV name from `data/`: `leads_training.csv`, `leads_testing.csv` or `leads_full_scale_100.csv` | `leads_full_scale_100.csv` |
| `reference_date` | The date treated as "today" for recency, as `YYYY-MM-DD` | `2024-01-21` |

Keep the defaults for your first run, then click **Trigger**. Each click makes a new **DAG run**, so you can run the testing file and then the full file one after the other.

**6. Watch it run.** Open the run you just started, and use the **Graph** or **Grid** tab. Each task box changes colour as it goes:

| Colour | State | Meaning |
|---|---|---|
| Grey | queued / scheduled | Waiting for its turn |
| Light green | running | Working right now |
| Dark green | success | Finished OK |
| Yellow / orange | up_for_retry | Crashed once. Airflow retries it after 1 minute |
| Red | failed | Crashed again after the retry. Check its logs |

A run on 100 leads takes a few seconds without an API key, and about a minute with one (most of that time is waiting for the LLM).

**7. Read the logs.** Click any task box and open the **Logs** tab. Each task logs what it did. For a 100-lead run, you'll see lines like these:

| Task | Typical log lines |
|---|---|
| `load_leads` | `Loaded 100 leads (0 with data issues)` |
| `score_leads` | `Decisions: {'qualified': 35, 'review': 23, 'rejected': 42}` |
| `write_outreach_messages` | `Writing outreach for 35 qualified leads`, then `Batch 1: LLM returned 10/10 messages` for each batch |
| `get_second_opinions` | `Getting AI second opinions for 23 review leads` |
| `build_report` | `Summary: {...}` and `Report written to .../output/leads_full_scale_100_report.json` |

Warnings worth knowing about:
- `NVIDIA_API_KEY not set - using template messages`: Airflow was started in a terminal without the key. Stop Airflow, run `export NVIDIA_API_KEY=...`, and start it again.
- `LLM attempt 1/4 failed: rate limited (429). Retrying in 2s`: normal on the free tier. The app waits and retries by itself.
- `Batch 2: LLM failed (...) - using templates for this batch`: the LLM failed 4 times, so that batch used template emails. The run still finishes.

**8. See what each task handed on (optional).** Click a task and open the **XCom** tab. "XCom" is how Airflow passes data between tasks: whatever a task returns is saved there and given to the next task. For example, `score_leads` shows every lead with its score, and `build_report` shows the path of the report it wrote. This is a good way to understand how the pipeline works step by step.

**9. Get the results.** When all 5 boxes are dark green, open the `output/` folder in the project. You'll find the two report files described in **Step 2** below. Each run overwrites the previous report for the same input file.

**10. Re-run a step (optional).** To run one task again, for example after changing a prompt, click the task, choose **Clear**, and confirm. Airflow re-runs that task and every task after it. To run everything again, just trigger a new run.

**Trigger from the terminal instead.** Open a second terminal, activate the venv, and set the same `AIRFLOW_HOME` first, so the command talks to the Airflow you started:

```bash
source .venv/bin/activate
export AIRFLOW_HOME="$PWD/airflow_home"

airflow dags trigger lead_qualification                                          # defaults
airflow dags trigger lead_qualification --conf '{"input_file": "leads_testing.csv"}'  # another file
airflow dags list-import-errors                                                   # why the DAG isn't showing
```

---

## Step 2: Read the results

Every run writes two files to `output/`. They're named after the input file.

| File | What's inside |
|---|---|
| `<input>_report.json` | `summary` (totals, qualified %, common rejection reasons), `priority_queue` (ranked qualified leads, each with its email), `flagged_for_review` (with an AI second opinion), `disqualified`, `sample_outreach_messages`, `all_leads` |
| `<input>_leads.csv` | One row per lead. You can open it in Excel or Google Sheets. |

To check that the LLM was actually used, look at `run_info.llm_used` and `summary.outreach_messages_written_by` in the JSON report. For example, `{"llm": 33, "template": 2}` means the LLM wrote 33 emails and 2 came from templates.

---

## Where to change things

- **Rubric points, thresholds and batch size:** `dags/lead_qualifier/settings.py`
- **LLM prompts and email tone variants:** `dags/lead_qualifier/ai_steps.py`
- **The order of the Airflow tasks:** `dags/lead_qualification_dag.py`
