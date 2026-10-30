"""
Step 1 - Load and clean the CSV.

Real-world data is messy. This step turns every row into a clean dictionary
and writes down any problem it found in `data_issues` instead of crashing.

Everything returned is plain strings/ints/None so Airflow can pass it to the
next task (Airflow stores task outputs as JSON, called "XCom").
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

from . import settings

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["name", "company", "company_size", "industry", "source", "last_interaction_date"]

# Values that really mean "we don't know"
MISSING_MARKERS = {"", "na", "n/a", "null", "none", "-", "unknown", "unknown source", "unknown sector"}


def clean_text(value):
    """Strip spaces and turn 'NA', 'Unknown', '' etc. into None."""
    value = (value or "").strip()
    return None if value.lower() in MISSING_MARKERS else value


def parse_company_size(value, issues):
    """'1,200' -> 1200. Returns None (and records an issue) if it isn't a valid number."""
    text = clean_text(value)
    if text is None:
        issues.append("missing company_size")
        return None
    try:
        size = int(float(text.replace(",", "")))
    except ValueError:
        issues.append(f"invalid company_size '{text}'")
        return None
    if size <= 0:
        issues.append(f"invalid company_size '{text}'")
        return None
    return size


def parse_date(value, issues):
    """Keep dates as 'YYYY-MM-DD' strings (JSON friendly). None if missing/invalid."""
    text = clean_text(value)
    if text is None:
        issues.append("missing last_interaction_date")
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        issues.append(f"invalid last_interaction_date '{text}'")
        return None


def resolve_input_path(input_file):
    """Accept either a full path or just a file name inside the data/ folder."""
    path = Path(input_file)
    if not path.is_absolute():
        path = settings.DATA_DIR / path
    return path


def load_leads(input_file):
    """Read the CSV and return a list of clean lead dictionaries."""
    path = resolve_input_path(input_file)
    log.info("Reading leads from %s", path)

    if not path.exists():
        # A missing input file is a real error - fail loudly so Airflow marks the task red.
        raise FileNotFoundError(f"Input file not found: {path}")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing_columns = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing_columns:
            raise ValueError(f"CSV is missing required columns: {missing_columns}")

        leads = []
        for row_number, row in enumerate(reader, start=2):  # row 1 is the header
            row = {(k or "").strip(): v for k, v in row.items()}

            # Skip rows that are completely empty
            if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
                continue

            issues = []
            name = clean_text(row.get("name"))
            company = clean_text(row.get("company"))
            industry = clean_text(row.get("industry"))
            source = clean_text(row.get("source"))
            if name is None:
                issues.append("missing name")
            if company is None:
                issues.append("missing company")
            if industry is None:
                issues.append("missing industry")
            if source is None:
                issues.append("missing source")

            leads.append({
                "lead_id": str(len(leads) + 1),    # string: safe as a JSON dict key later
                "csv_row": row_number,
                "name": name,
                "first_name": name.split()[0] if name else None,
                "company": company,
                "company_size": parse_company_size(row.get("company_size"), issues),
                "industry": industry,
                "source": source,
                "last_interaction_date": parse_date(row.get("last_interaction_date"), issues),
                "data_issues": issues,
            })

    with_issues = sum(1 for lead in leads if lead["data_issues"])
    log.info("Loaded %d leads (%d with data issues)", len(leads), with_issues)
    return leads
