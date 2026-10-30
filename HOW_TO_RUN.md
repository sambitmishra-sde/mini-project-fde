# How to Run the Lead Qualification App

This is the only setup guide you need. There are two ways to run the app:

- **Option A: plain Python.** Quickest. You don't need Airflow.
- **Option B: Airflow.** The same pipeline as a DAG you trigger from the Airflow web UI.

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

Never put the key in a file you commit.

**Optional: use a different model.** The default model is `nvidia/nemotron-3.5-lightning-30b-a3b`. To use another model, copy its id from its page on build.nvidia.com:
```bash
export NVIDIA_MODEL="meta/llama-3.3-70b-instruct"
```

**No key?** The app still runs. Emails then come from built-in templates, which still use each lead's details, instead of the LLM.

---

## Option A: Run with plain Python (no Airflow)

Requires **Python 3.9 or newer**. You can skip `requirements.txt` for this option. The app uses only the Python standard library, and that file only installs Airflow (needed for Option B2).

Run these commands from the project folder (`mini-project-fde/`):

```bash
# 1. Try the prompts on 5 leads first (a quick, cheap check)
python run_local.py --input leads_training.csv --limit 5

# 2. Robustness check on the messy edge-case file
python run_local.py --input leads_testing.csv

# 3. The full 100-lead run (this is the default file)
python run_local.py
```

At the end of each run, the app prints `Done. Report: output/...`.

Options:

| Flag | Meaning | Default |
|---|---|---|
| `--input` | A CSV file name in `data/`, or a full path | `leads_full_scale_100.csv` |
| `--limit N` | Only process the first N leads | all leads |
| `--reference-date` | The date treated as "today" when scoring recency | `2024-01-21` |

---

## Option B: Run in Airflow

### B1. With Docker (recommended, works on any OS)

Requires Docker Desktop or Docker Engine. Run this single command from the project folder:

```bash
docker run -it --rm -p 8080:8080 \
  --user "$(id -u):0" \
  -e AIRFLOW__CORE__LOAD_EXAMPLES=False \
  -e AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True \
  -e LEAD_PROJECT_DIR=/opt/airflow/project \
  -e NVIDIA_API_KEY \
  -e NVIDIA_MODEL \
  -v "$PWD/dags:/opt/airflow/dags" \
  -v "$PWD/data:/opt/airflow/project/data" \
  -v "$PWD/output:/opt/airflow/project/output" \
  apache/airflow:3.3.2 standalone
```

On Windows PowerShell, use the same command with these changes:
- Remove the `--user` line.
- Replace `$PWD` with `${PWD}`.
- Replace each `\` at the end of a line with a backtick (`` ` ``).

What the settings do:
- `standalone` runs the whole of Airflow (web UI, scheduler and database) in one container. This is for learning only, not for production.
- `SIMPLE_AUTH_MANAGER_ALL_ADMINS=True` skips the login page. Only use this on your own machine.
- `-e NVIDIA_API_KEY` passes the key from your terminal into the container.
- The three `-v` lines share your `dags/`, `data/` and `output/` folders with the container. Reports are written straight into your own `output/` folder.

Wait about a minute until the log shows Airflow is ready, then continue with **B3**. Press `Ctrl+C` to stop.

### B2. Without Docker (macOS / Linux / WSL)

Airflow does not run natively on Windows. Windows users should use WSL or Option B1.

```bash
# 1. Create an isolated Python environment (needs Python 3.10 - 3.14)
python3 -m venv .venv && source .venv/bin/activate
hash -r                       # make the shell forget any cached global `pip`
which python                  # must end in .../mini-project-fde/.venv/bin/python
python --version

# 2. Upgrade pip INSIDE the venv (old pip crashes on Python 3.12+)
#    Always use `python -m pip`, never plain `pip`: it guarantees the venv's pip runs.
python -m pip install --upgrade pip setuptools

# 3. Install requirements.txt, together with Airflow's official constraints file
#    for YOUR Python version. PY becomes e.g. "3.12", detected automatically.
PY=$(python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
python -m pip install -r requirements.txt --constraint \
  "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-${PY}.txt"

# 4. Check that it worked (should print 3.3.2)
airflow version

# 5. Start Airflow
export AIRFLOW_HOME="$PWD/airflow_home"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True
airflow standalone
```

### B3. Trigger the DAG in the web UI

1. Open http://localhost:8080.
2. Find the DAG **`lead_qualification`**. If it isn't there yet, wait about 30 seconds and refresh.
3. Click **Trigger**. A form appears where you can change:
   - `input_file`: for example `leads_testing.csv`
   - `reference_date`
4. Open the run and switch to the **Graph** view. Each box turns green when its task succeeds:
   ```
   load_leads -> score_leads -> write_outreach_messages ─┐
                             └> get_second_opinions ─────┴> build_report
   ```
5. Click any task and open **Logs** to see what it did, such as batch progress, retries and decision counts.

You can also trigger the DAG from a terminal:
```bash
airflow dags trigger lead_qualification
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

## Troubleshooting

| You see | What to do |
|---|---|
| `NVIDIA_API_KEY not set - using template messages` | Set the key (Step 1) in the **same** terminal you run from. For Docker, set the key before running `docker run`. |
| `HTTP 401` or `HTTP 403 (check NVIDIA_API_KEY)` | The key is wrong or has expired. Create a new key on build.nvidia.com. |
| `HTTP 404 (model ... not found)` | The model was renamed or retired. Pick a current chat model on build.nvidia.com and set `NVIDIA_MODEL`. |
| `rate limited (429). Retrying...` | This is normal on the free tier. The app waits and retries by itself. |
| `Gave up after 4 attempts` | The app used templates for that batch and carried on. Run it again later. |
| The DAG doesn't appear in Airflow | Check that `dags/` is mounted or set as the DAGs folder. Errors in the DAG file show at the top of the Airflow UI. |
| `Permission denied` writing to `output/` (Docker on Linux) | Keep the `--user "$(id -u):0"` line in the command. |
| `AttributeError: module 'pkgutil' has no attribute 'ImpImporter'` | An old, global pip is running, not the venv's pip. Check whether the traceback shows a path outside `.venv`. Delete and recreate `.venv`, run `hash -r`, then `python -m pip install --upgrade pip`. Always use `python -m pip`. |
| `pip install` fails with a 404 on the constraints URL | Your Python version isn't supported. Use Python 3.10 - 3.14 (check with `python --version`). |
| `requirements.txt` not found | It's on the `feature/airflow-lead-qualification` branch until PR #1 is merged. Run `git checkout feature/airflow-lead-qualification` first. |
| `Input file not found` | The file must be in `data/`, or you must pass a full path. |

---

## Where to change things

- **Rubric points, thresholds and batch size:** `dags/lead_qualifier/settings.py`
- **LLM prompts and email tone variants:** `dags/lead_qualifier/ai_steps.py`
- **The order of the Airflow tasks:** `dags/lead_qualification_dag.py`
