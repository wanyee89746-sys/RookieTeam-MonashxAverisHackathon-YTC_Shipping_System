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

FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg"
]

_PROMPT = """Extract these 7 fields from the shipping document text below.
Field labels vary (e.g. "Load Port" == "Port of Loading", "To the Order of" == "Consignee") —
match by MEANING, not exact header text, but ONLY when the label is a genuine synonym.

Fields: {fields}

CRITICAL RULE: If the requested information is not explicitly present in the text,
return null. Do not guess, infer, calculate, or use outside knowledge. Do not fill in
a "plausible" value. Do not average, sum, or derive a value from other numbers unless
the text itself states that exact field. A placeholder like "???", "___", "TBA", "TBC",
"N/A" is NOT a value — return null for it, not the placeholder text.

- shipper/consignee/notify_party: exact company name as written, or null
- port_of_loading/port_of_discharge: exact place name as written, or null
- container_count: integer explicitly stated (e.g. "3 x 40'HC" -> 3), or null if not stated
- gross_weight_kg: integer in KG explicitly stated (strip commas/units only, do not convert
  units or recalculate), or null if not stated

Document text:
---
{text}
---

Respond with ONLY this JSON, no markdown fences:
{{"shipper": ..., "consignee": ..., "notify_party": ..., "port_of_loading": ...,
  "port_of_discharge": ..., "container_count": ..., "gross_weight_kg": ...,
  "extraction_notes": "<anything odd: blank fields, garbled text, wrong doc type>"}}
"""


def extract_fields(text: str) -> dict:

    prompt = _PROMPT.format(
        fields=", ".join(FIELDS),
        text=text[:6000]
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

        return {
            k: data.get(k)
            for k in FIELDS
        } | {
            "extraction_notes": data.get(
                "extraction_notes",
                ""
            )
        }

    except Exception:
        # Fail-safe:
        # Return null for all fields if Gemini's response
        # cannot be parsed.
        return {
            k: None
            for k in FIELDS
        } | {
            "extraction_notes": "parse_error"
        }