import os
import json
import time
import re

from dotenv import load_dotenv
from google import genai

# Load .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Create Gemini client
client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)

GEMINI_MODEL = "gemini-3.5-flash-lite"

CATEGORIES = [
    "BL_COMPARISON",
    "SI_REQUEST",
    "INVOICE_QUERY",
    "GENERAL",
    "SPAM"
]


# =========================================================
# GEMINI FALLBACK PROMPT
# =========================================================

_PROMPT = """You classify shipping-ops emails into exactly one category.

Categories:

- SI_REQUEST:
  The email provides, sends, submits, or requests a Shipping Instruction (SI).

- BL_COMPARISON:
  The email explicitly asks to compare, check, verify, or confirm
  information between an SI and a draft BL / BL.

- INVOICE_QUERY:
  Billing, GR, invoice cancellation, D&D/local charges, freight queries,
  payment queries, or other invoice-related questions.

- GENERAL:
  Internal updates, berthing reports, reminders, HR, RPA bot notices,
  operational information, or other normal business emails.

- SPAM:
  Prizes, phishing, scams, unrelated marketing, or unrelated spam.

Classification priority:

1. If the current email explicitly asks to compare/check/confirm SI against
   a draft BL, classify as BL_COMPARISON.
2. Otherwise, if the current email provides/sends/submits a Shipping
   Instruction, classify as SI_REQUEST.
3. Otherwise classify according to the remaining categories.

Do not classify an email as BL_COMPARISON merely because it contains
the words "draft BL".

Judge the purpose of the CURRENT email, not quoted/replied text.

Subject: {subject}
From: {frm}
Body: {body}

Respond with ONLY this JSON:
{{"category": "<one of {cats}>", "confidence": <0-1 float>, "reasoning": "<one sentence>"}}
"""


# =========================================================
# PYTHON RULE-BASED CLASSIFICATION
# =========================================================

def _clean_text(text: str) -> str:
    """Normalize email text for rule matching."""
    text = text or ""
    text = text.upper()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _rule_classify(email: dict) -> dict | None:
    """
    Try to classify obvious emails without using Gemini.

    Returns a classification dictionary when confidence is high.
    Returns None when Gemini should handle the email.
    """

    subject = _clean_text(email.get("subject", ""))
    body = _clean_text(email.get("body", ""))

    text = f"{subject} {body}"

    # ---------------------------------------------------------
    # 1. SPAM
    # ---------------------------------------------------------

    spam_patterns = [
        "CONGRATULATIONS YOU HAVE WON",
        "YOU HAVE WON",
        "YOU ARE A WINNER",
        "CLAIM YOUR PRIZE",
        "CLAIM YOUR REWARD",
        "FREE GIFT",
        "LOTTERY",
        "URGENT PAYMENT",
        "VERIFY YOUR ACCOUNT",
        "CLICK HERE TO CLAIM",
        "NIGERIAN PRINCE",
    ]

    if any(pattern in text for pattern in spam_patterns):
        return {
            "category": "SPAM",
            "confidence": 0.99,
            "reasoning": "Rule-based detection identified clear spam indicators."
        }

    # ---------------------------------------------------------
    # 2. BL_COMPARISON
    # ---------------------------------------------------------

    comparison_patterns = [
        "COMPARE THE SI AND DRAFT BL",
        "COMPARE SI AND DRAFT BL",
        "COMPARE THE SI WITH THE DRAFT BL",
        "COMPARE SI WITH DRAFT BL",
        "CHECK SI AGAINST DRAFT BL",
        "CHECK THE SI AGAINST THE DRAFT BL",
        "CHECK SI VS BL",
        "CHECK THE SI VS BL",
        "SI AND DRAFT BL",
        "SI VS BL",
        "SI AGAINST BL",
        "CONFIRM SI AND BL MATCH",
        "CONFIRM WHETHER SI AND BL MATCH",
        "CHECK WHETHER SI AND BL MATCH",
        "COMPARE SI WITH BL",
        "COMPARE THE SI WITH BL",
        "SEND DRAFT BL FOR CHECKING",
        "SEND THE DRAFT BL FOR CHECKING",
        "DRAFT BL FOR CHECKING",
    ]

    if any(pattern in text for pattern in comparison_patterns):
        return {
            "category": "BL_COMPARISON",
            "confidence": 0.98,
            "reasoning": "The email explicitly requests SI and BL comparison or checking."
        }

    # More general comparison wording.
    has_si = "SI" in text or "SHIPPING INSTRUCTION" in text
    has_bl = "BL" in text or "BILL OF LADING" in text
    comparison_words = [
        "COMPARE",
        "CHECK",
        "VERIFY",
        "CONFIRM",
        "MATCH",
        "CHECKING",
    ]

    if has_si and has_bl and any(word in text for word in comparison_words):
        return {
            "category": "BL_COMPARISON",
            "confidence": 0.90,
            "reasoning": "The email contains SI and BL references together with comparison/checking language."
        }

    # ---------------------------------------------------------
    # 3. SI_REQUEST
    # ---------------------------------------------------------

    si_patterns = [
        "PLEASE FIND SHIPPING INSTRUCTION",
        "PLEASE FIND SHIPPING INSTRUCTIONS",
        "PLEASE FIND SI",
        "SHIPPING INSTRUCTION FOR",
        "SHIPPING INSTRUCTIONS FOR",
        "CUST SI",
        "CUSTOMER SI",
        "HEREWITH SI",
        "HERE IS THE SI",
        "ATTACHED SI",
        "ATTACH SI",
        "SUBMIT SI",
        "SUBMISSION OF SI",
    ]

    if any(pattern in text for pattern in si_patterns):
        return {
            "category": "SI_REQUEST",
            "confidence": 0.98,
            "reasoning": "The email clearly provides or submits a Shipping Instruction."
        }

    # Strong SI field combination.
    si_field_signals = [
        "SHIPPER",
        "CONSIGNEE",
        "NOTIFY PARTY",
        "PORT OF LOADING",
        "PORT OF DISCHARGE",
        "GROSS WEIGHT",
    ]

    si_signal_count = sum(signal in text for signal in si_field_signals)

    if si_signal_count >= 4 and has_si:
        # "draft BL" alone should not turn this into comparison.
        return {
            "category": "SI_REQUEST",
            "confidence": 0.95,
            "reasoning": "The email contains multiple Shipping Instruction fields and is providing SI information."
        }
    # ---------------------------------------------------------
    # 4. INVOICE_QUERY
    # ---------------------------------------------------------

    invoice_patterns = [
        "INVOICE",
        "INVOICING",
        "CREDIT NOTE",
        "DEBIT NOTE",
        "D&D CHARGE",
        "D&D CHARGES",
        "DEMURRAGE",
        "DETENTION",
        "LOCAL CHARGE",
        "LOCAL CHARGES",
        "FREIGHT CHARGE",
        "FREIGHT QUERY",
        "PAYMENT QUERY",
        "PAYMENT STATUS",
        "GR QUERY",
    ]

    if any(pattern in text for pattern in invoice_patterns):

        # Shipping Instruction / BL emails take priority
        # over invoice words that may appear inside the document.
        if (
            "SHIPPING INSTRUCTION" in text
            or "CUST SI" in text
            or "SI REQUEST" in text
            or "SI AND DRAFT BL" in text
            or "COMPARE SI" in text
            or "COMPARE THE SI" in text
        ):
            return None

    # ---------------------------------------------------------
    # 5. GENERAL
    # ---------------------------------------------------------

    general_patterns = [
        "BERTHING",
        "BERTHED",
        "VESSEL ARRIVAL",
        "VESSEL DEPARTURE",
        "OPERATIONAL UPDATE",
        "RPA BOT",
        "AUTOMATED NOTIFICATION",
        "REMINDER",
        "MEETING REMINDER",
    ]

    if any(pattern in text for pattern in general_patterns):
        return {
            "category": "GENERAL",
            "confidence": 0.90,
            "reasoning": "Rule-based detection identified a routine operational or administrative email."
        }

    # No strong rule → use Gemini.
    return None


# =========================================================
# GEMINI CLASSIFICATION
# =========================================================

def _gemini_classify(email: dict) -> dict:

    prompt = _PROMPT.format(
        subject=email.get("subject", ""),
        frm=email.get("from", ""),
        body=(email.get("body", "") or "")[:2000],
        cats=" | ".join(CATEGORIES),
    )

    for attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            break

        except Exception as e:
            error_text = str(e)

            if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                wait_time = 10 * (attempt + 1)

                print(
                    f"Gemini quota reached. "
                    f"Waiting {wait_time} seconds before retry..."
                )

                time.sleep(wait_time)

            else:
                if attempt == 4:
                    raise

                wait_time = 2 ** attempt

                print(
                    f"Gemini request failed. "
                    f"Retrying in {wait_time} seconds..."
                )

                time.sleep(wait_time)

    else:
        raise RuntimeError(
            "Gemini request failed after all retries."
        )

    try:
        data = json.loads(resp.text)

        if data["category"] not in CATEGORIES:
            raise ValueError(data["category"])

        return data

    except Exception:
        return {
            "category": "GENERAL",
            "confidence": 0.0,
            "reasoning": "parse_error"
        }


# =========================================================
# PUBLIC FUNCTION
# =========================================================

def classify(email: dict) -> dict:
    """
    Classify email.

    First attempt:
        Python rule-based classification.

    Fallback:
        Gemini for ambiguous emails.
    """

    rule_result = _rule_classify(email)

    if rule_result is not None:
        print(
            f"[RULE] {email.get('email_id', '?')} "
            f"-> {rule_result['category']}"
        )
        return rule_result

    print(
        f"[GEMINI] {email.get('email_id', '?')} "
        f"-> ambiguous, using Gemini"
    )

    return _gemini_classify(email)