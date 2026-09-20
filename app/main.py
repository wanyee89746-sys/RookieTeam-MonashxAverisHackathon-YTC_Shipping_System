from fastapi import FastAPI
from data.loader import Inbox

app = FastAPI()

inbox = Inbox("data")


@app.get("/health")
def health_check():
    """Check whether the API server is running."""
    return {"status": "ok"}


@app.get("/emails")
def get_emails():
    """Return all emails for the frontend."""
    return inbox.emails()