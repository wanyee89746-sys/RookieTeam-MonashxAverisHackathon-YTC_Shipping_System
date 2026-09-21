from pathlib import Path
import json
import sys

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


# ============================================================
# EMAIL LIST
# ============================================================

@app.get("/emails")
def get_emails():
    """
    Return the inbox emails together with their real
    verification results.
    """

    submission = load_submission()

    result = []

    for email in inbox.emails():

        email_id = email["email_id"]

        report = submission.get(email_id, {})

        result.append({
            "email_id": email_id,
            "subject": email.get("subject", ""),
            "from": email.get("from", ""),

            "category": report.get(
                "category",
                "GENERAL"
            ),

            "status": report.get(
                "status",
                "OK"
            ),

            "review_reason": report.get(
                "review_reason"
            ),

            "defect_fields": report.get(
                "defect_fields",
                []
            ),

            "has_defect": report.get(
                "has_defect",
                False
            ),
        })

    return result


# ============================================================
# EMAIL REPORT
# ============================================================

@app.get("/emails/{email_id}/report")
def get_report(email_id: str):
    """
    Return the complete verification report for one email.

    This includes:
    - category
    - status
    - review reason
    - defect fields
    - field comparison results
    - SI values
    - BL values
    """

    submission = load_submission()

    if email_id not in submission:
        raise HTTPException(
            status_code=404,
            detail=f"No report found for {email_id}"
        )

    report = submission[email_id]

    return {
        "email_id": email_id,
        **report
    }
