import os
import json
import time

from dotenv import load_dotenv
from google import genai

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Create Gemini client
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)

GEMINI_MODEL = "gemini-3.6-flash"

CATEGORIES = [
    "BL_COMPARISON",
    "SI_REQUEST",
    "INVOICE_QUERY",
    "GENERAL",
    "SPAM"
]

_PROMPT = """You classify shipping-ops emails into exactly one category.

Categories:
- BL_COMPARISON: asks to compare/check/confirm SI vs draft BL, or send a draft BL for checking
- SI_REQUEST: asks for a Shipping Instruction to be issued/sent
- INVOICE_QUERY: billing, GR, invoice cancellation, D&D/local charges, freight queries
- GENERAL: internal updates, berthing reports, reminders, HR, RPA bot notices
- SPAM: prizes, phishing, unrelated marketing

Subject: {subject}
From: {frm}
Body: {body}

Respond with ONLY this JSON, no markdown fences:
{{"category": "<one of {cats}>", "confidence": <0-1 float>, "reasoning": "<one sentence>"}}
"""


def classify(email: dict) -> dict:

    prompt = _PROMPT.format(
        subject=email.get("subject", ""),
        frm=email.get("from", ""),
        body=(email.get("body", "") or "")[:2000],
        cats=" | ".join(CATEGORIES),
    )

    # Try Gemini up to 3 times
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                },
            )

            # Successful request
            break

        except Exception as e:

            # If this was the last attempt, raise the error
            if attempt == 2:
                raise

            # Wait longer after each failed attempt
            wait_time = 2 ** attempt

            print(
                f"Gemini request failed. "
                f"Retrying in {wait_time} seconds..."
            )

            time.sleep(wait_time)

    try:
        data = json.loads(resp.text)

        # Make sure Gemini returned a valid category
        if data["category"] not in CATEGORIES:
            raise ValueError(data["category"])

        return data

    except Exception:
        # Fail-safe:
        # Don't crash the whole pipeline because Gemini returned
        # invalid JSON or an invalid category.
        return {
            "category": "GENERAL",
            "confidence": 0.0,
            "reasoning": "parse_error"
        }