import json
import sys
import os

from pathlib import Path
from datetime import datetime, timezone
from functools import lru_cache
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException


# ============================================================
# PATHS
# ============================================================

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

# Make sure Python can import files inside app/
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


from loader import Inbox


# ============================================================
# APP SETUP
# ============================================================

app = FastAPI(
    title="Shipping Document Verification API"
)

inbox = Inbox(str(DATA_DIR))

SUBMISSION_PATH = PROJECT_DIR / "submission.json"

OVERRIDES_PATH = PROJECT_DIR / "overrides.json"

FIELDS = [
    "shipper", "consignee", "notify_party", "port_of_loading",
    "port_of_discharge", "container_count", "gross_weight_kg",
]


def load_overrides():
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_overrides(data):
    OVERRIDES_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def apply_override(report, ov):
    """Merge reviewer decisions over the computed result."""
    report = dict(report)
    ov = ov or {}

    report["resolved"] = bool(ov.get("resolved"))
    report["note"] = ov.get("note", "")
    corrections = ov.get("corrections")
    report["reviewed"] = bool(corrections)

    if not corrections:
        return report

    from comparator import compare_detailed

    values = {
        f: dict(v)
        for f, v in (report.get("field_values") or {}).items()
    }
    for f, c in corrections.items():
        values.setdefault(f, {"si": None, "bl": None}).update(c)

    d = compare_detailed(
        {f: values.get(f, {}).get("si") for f in FIELDS},
        {f: values.get(f, {}).get("bl") for f in FIELDS},
    )

    report["original_status"] = report.get("status")
    report.update(
        field_values=d["field_values"],
        field_results=d["field_results"],
        defect_fields=d["defect_fields"],
        has_defect=d["has_defect"],
        status="MISMATCH" if d["has_defect"] else "OK",
        review_reason=None,
    )
    return report


# ============================================================
# LOAD VERIFICATION RESULTS
# ============================================================

def load_submission():
    """
    Load the generated verification results from submission.json.

    The actual document verification is still handled by
    pipeline.py. This API only serves the verified results
    to the frontend.
    """

    if not SUBMISSION_PATH.exists():
        return {}

    try:
        with open(SUBMISSION_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return {}


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check():
    return {
        "status": "ok"
    }

@app.get("/debug-data")
def debug_data():
    inbox_dir = DATA_DIR / "inbox"

    return {
        "app_dir": str(APP_DIR),
        "project_dir": str(PROJECT_DIR),
        "data_dir": str(DATA_DIR),
        "current_working_dir": os.getcwd(),
        "data_exists": DATA_DIR.exists(),
        "inbox_exists": inbox_dir.exists(),
        "inbox_file_count": len(list(inbox_dir.glob("email_*.json")))
            if inbox_dir.exists()
            else 0,
    }
# ============================================================
# EMAIL LIST
# ============================================================

@app.get("/emails")
def get_emails():
    submission = load_submission()
    overrides = load_overrides()
    result = []

    for email in inbox.emails():
        email_id = email["email_id"]
        report = apply_override(
            submission.get(email_id, {}), overrides.get(email_id)
        )

        result.append({
            "email_id": email_id,
            "subject": email.get("subject", ""),
            "from": email.get("from", ""),
            "attachments": email.get("attachments", []),
            "category": report.get("category", "GENERAL"),
            "status": report.get("status", "OK"),
            "review_reason": report.get("review_reason"),
            "defect_fields": report.get("defect_fields", []),
            "has_defect": report.get("has_defect", False),
            "resolved": report["resolved"],
            "reviewed": report["reviewed"],
        })

    return result

@lru_cache(maxsize=600)
def _fresh_values(email_id):
    """Recompute SI/BL values for entries saved before field_values existed."""
    try:
        from pipeline import process_comparison
        fresh = process_comparison(inbox, inbox.get(email_id))
        return fresh.get("field_values") or {}
    except Exception as e:
        print(f"[values] {email_id}: {e}")
        return {}
    
@app.get("/emails/{email_id}/report")
def get_report(email_id: str):
    submission = load_submission()

    if email_id not in submission:
        raise HTTPException(404, f"No report found for {email_id}")

    report = dict(submission[email_id])

    if report.get("category") == "BL_COMPARISON" and not report.get("field_values"):
        vals = _fresh_values(email_id)
        if vals:
            report["field_values"] = {f: dict(v) for f, v in vals.items()}

    report = apply_override(report, load_overrides().get(email_id))
    return {"email_id": email_id, **report}


@app.get("/emails/{email_id}/raw")
def get_raw(email_id: str):
    """The email as received, before any pipeline processing."""
    try:
        return inbox.get(email_id)
    except Exception:
        raise HTTPException(404, f"No email {email_id}")


@lru_cache(maxsize=256)
def _attachment_text(path):
    try:
        from pipeline import read_attachment_text
        return read_attachment_text(inbox, path) or ""
    except Exception:
        return ""


@app.get("/emails/{email_id}/evidence")
def get_evidence(email_id: str):
    """Extracted SI/BL text, shown to the reviewer as source evidence."""
    try:
        atts = inbox.get(email_id).get("attachments", [])
    except Exception:
        raise HTTPException(404, f"No email {email_id}")

    si = next((a for a in atts if "_SI" in a), None)
    bl = next((a for a in atts if "_BL" in a), None)

    return {
        "si_path": si,
        "bl_path": bl,
        "si_text": _attachment_text(si)[:3000] if si else "",
        "bl_text": _attachment_text(bl)[:3000] if bl else "",
    }


class ReviewIn(BaseModel):
    corrections: dict = {}
    note: str = ""


class ResolveIn(BaseModel):
    resolved: bool = True
    note: str = ""


@app.post("/emails/{email_id}/review")
def save_review(email_id: str, body: ReviewIn):
    if email_id not in load_submission():
        raise HTTPException(404, f"No report found for {email_id}")

    overrides = load_overrides()
    entry = overrides.get(email_id, {})
    entry["corrections"] = {**entry.get("corrections", {}), **body.corrections}
    entry["note"] = body.note or entry.get("note", "")
    entry["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    overrides[email_id] = entry
    save_overrides(overrides)
    return {"ok": True}


@app.post("/emails/{email_id}/resolve")
def resolve(email_id: str, body: ResolveIn):
    if email_id not in load_submission():
        raise HTTPException(404, f"No report found for {email_id}")

    overrides = load_overrides()
    entry = overrides.get(email_id, {})
    entry["resolved"] = body.resolved
    entry["note"] = body.note or entry.get("note", "")
    entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
    overrides[email_id] = entry
    save_overrides(overrides)
    return {"ok": True}