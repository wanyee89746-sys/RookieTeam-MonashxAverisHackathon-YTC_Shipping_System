from fastapi import FastAPI
import sys
sys.path.append("/app/data")

from loader import Inbox

app = FastAPI()
inbox = Inbox("/app/data")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/emails")
def get_emails():
    emails = inbox.emails()
    return [
        {"email_id": e["email_id"], "subject": e["subject"], "category": "GENERAL"}
        for e in emails
    ]


@app.get("/emails/{email_id}/report")
def get_report(email_id: str):
    return {
        "email_id": email_id,
        "category": "GENERAL",
        "status": "OK",
        "review_reason": None,
        "defect_fields": [],
        "has_defect": False,
    }