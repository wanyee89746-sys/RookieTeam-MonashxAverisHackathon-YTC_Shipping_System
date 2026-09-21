import email
import os
import json
import re

from dotenv import load_dotenv
from google import genai

from ratelimit_cache import RateLimiter, LLMCache, call_with_backoff

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
GEMINI_MODEL = "gemini-3.5-flash-lite"

CATEGORIES = [
    "BL_COMPARISON",
    "SI_REQUEST",
    "INVOICE_QUERY",
    "GENERAL",
    "SPAM",
]

_limiter = RateLimiter(calls_per_minute=12)
_cache = LLMCache()


_FEWSHOT = """
Examples (illustrating INTENT, not exact wording — real emails vary a lot):

1) "Please compare the attached SI and draft BL and flag any mismatch."
   -> BL_COMPARISON

2) "Attached is the shipping instruction for booking XYZ. Please issue the draft BL."
   -> SI_REQUEST

3) "The GR is still missing on invoice 12345, please advise."
   -> INVOICE_QUERY

4) "Vessel berthed on schedule, documents to follow. FYI only."
   -> GENERAL

5) "You've won a prize! Click here to claim."
   -> SPAM

6) "I have an urgent business proposal involving millions of dollars.
   Please reply with your bank details."
   -> SPAM
"""


_PROMPT = """You classify shipping-operations emails into exactly one category,
based on the sender's INTENT, not on specific phrases or subject-line codes.

Categories:
- SI_REQUEST: provides/submits/sends a Shipping Instruction, or asks for one.
- BL_COMPARISON: explicitly asks to compare/check/verify SI against a draft BL.
- INVOICE_QUERY: billing, GR, invoice, D&D/detention, local charges, freight/payment questions.
- GENERAL: internal updates, reports, reminders, HR, automated/bot notices.
- SPAM: prizes, phishing, unrelated marketing/scams, unsolicited fraudulent business
  proposals, requests for sensitive financial information from suspicious/unrelated senders.

{fewshot}

Important:
- Classify the CURRENT email only.
- Ignore quoted/forwarded thread content when judging intent unless the current message has no content of its own.
- A subject containing "invoice" or "payment" does NOT automatically make an email an INVOICE_QUERY.
- If the actual current message is an unsolicited business proposal asking for
  bank details or other sensitive financial information, classify it as SPAM
  even if the subject contains invoice/payment wording.
- Do not invent facts.
- Return exactly one category per email.

Return a JSON array, one object per input email, IN THE SAME ORDER:

{{"id": "<email_id>", "category": "<one of {cats}>",
"confidence": <0-1>, "reasoning": "<one short sentence>"}}

EMAILS:
{emails_block}
"""


def _clean_text(text: str) -> str:
    text = (text or "").upper()
    return re.sub(r"\s+", " ", text).strip()


def _rule_classify(email: dict) -> dict | None:
    subject = _clean_text(email.get("subject", ""))
    body = _clean_text(email.get("body", ""))

    text = subject + " " + body

    # ---------------------------------------------------------
    # SPAM / SCAM
    # ---------------------------------------------------------
    #
    # These rules are intentionally based on combinations of
    # suspicious intent signals rather than email IDs.
    #
    # This check must happen BEFORE invoice classification because
    # scam emails can deliberately use words such as "invoice" or
    # "payment" in their subject.
    # ---------------------------------------------------------

    strong_spam_patterns = [
        "YOU HAVE WON",
        "CLAIM YOUR PRIZE",
        "CLAIM YOUR REWARD",
        "FREE GIFT",
        "LOTTERY",
        "VERIFY YOUR ACCOUNT",
        "CLICK HERE TO CLAIM",
        "NIGERIAN PRINCE",
        "GUARANTEED RETURNS",
    ]

    if any(pattern in text for pattern in strong_spam_patterns):
        return {
            "category": "SPAM",
            "confidence": 0.97,
            "reasoning": "rule: strong spam/scam markers",
            "method": "RULE",
        }

    # Unsolicited financial/business proposal asking for bank
    # information is a strong scam/phishing pattern.
    #
    # Require multiple signals so normal payment/invoice emails
    # containing only one of these words are not incorrectly marked
    # as spam.
    has_business_proposal = any(
        phrase in text
        for phrase in [
            "BUSINESS PROPOSAL",
            "BUSINESS OPPORTUNITY",
            "INVESTMENT PROPOSAL",
            "URGENT BUSINESS",
            "BUSINESS DEAL",
            "BUSINESS TRANSACTION",
        ]
    )

    has_large_money_signal = bool(
        re.search(
            r"(?:USD|US\$|\$|EUR|GBP|RM|MYR)\s*"
            r"(?:\d[\d,]*(?:\.\d+)?)\s*"
            r"(?:MILLION|BILLION|MN|BN)?",
            text,
            flags=re.IGNORECASE,
        )
    )

    asks_for_bank_details = any(
        phrase in text
        for phrase in [
            "BANK DETAILS",
            "BANKING DETAILS",
            "BANK ACCOUNT DETAILS",
            "BANK INFORMATION",
            "ACCOUNT DETAILS",
            "BANK ACCOUNT",
        ]
    )

    urgent_language = any(
        phrase in text
        for phrase in [
            "URGENT",
            "URGENTLY",
            "IMMEDIATELY",
            "AS SOON AS POSSIBLE",
        ]
    )

    if (
        has_business_proposal
        and asks_for_bank_details
        and (has_large_money_signal or urgent_language)
    ):
        return {
            "category": "SPAM",
            "confidence": 0.98,
            "reasoning": "rule: unsolicited financial proposal requesting bank details",
            "method": "RULE",
        }

    # ---------------------------------------------------------
    # BL COMPARISON
    # ---------------------------------------------------------

    # A draft BL being sent for checking/review is a comparison intent,
    # even when the email does not explicitly mention "SI".
    has_si = (
        "SHIPPING INSTRUCTION" in text
        or "SUBMIT SI" in text
        or "PLEASE FIND SHIPPING INSTRUCTION" in text
        or "ATTACHED SI" in text
    )

    has_bl = (
        "DRAFT BL" in text
        or "BL" in text
        or "BILL OF LADING" in text
        or "DRAFT BILL OF LADING" in text
    )

    compare_words = [
        "COMPARE",
        "CHECK",
        "CHECKING",
        "VERIFY",
        "CONFIRM MATCH",
        "AGAINST",
        "MATCH",
        "MATCHES",
        "CORRESPOND",
        "CONSISTENT",
    ]

    if has_bl and any(w in text for w in compare_words):
        return {
            "category": "BL_COMPARISON",
            "confidence": 0.95,
            "reasoning": "rule: draft BL/checking intent",
            "method": "RULE",
        }

    # ---------------------------------------------------------
    # SI REQUEST
    # ---------------------------------------------------------
    si_provide_words = [
        "PLEASE FIND SHIPPING INSTRUCTION",
        "ATTACHED SI",
        "SUBMIT SI",
        "HEREWITH SI",
        "SHIPPING INSTRUCTION ATTACHED",
        "PLEASE FIND SI",
    ]

    # General operational reminders should not be classified as SI_REQUEST
    # merely because they contain "submit SI".
    is_reminder = (
        "REMINDER" in text
        or "PENDING SHIPMENTS" in text
        or "END OF DAY" in text
        or "OUTSTANDING LIST" in text
    )

    if is_reminder:
        return {
            "category": "GENERAL",
            "confidence": 0.90,
            "reasoning": "rule: operational reminder",
            "method": "RULE",
        }

    if any(w in body for w in si_provide_words):
        return {
            "category": "SI_REQUEST",
            "confidence": 0.90,
            "reasoning": "rule: SI provided/submitted",
            "method": "RULE",
        }

    # ---------------------------------------------------------
    # INVOICE
    # ---------------------------------------------------------
    invoice_words = [
        "INVOICE",
        "D&D CHARGE",
        "DEMURRAGE",
        "DETENTION",
        "LOCAL CHARGE",
        "GR QUERY",
        "PAYMENT QUERY",
    ]

    if any(w in text for w in invoice_words) and not has_bl:
        return {
            "category": "INVOICE_QUERY",
            "confidence": 0.85,
            "reasoning": "rule: billing vocabulary",
            "method": "RULE",
        }

    # ---------------------------------------------------------
    # GENERAL
    # ---------------------------------------------------------
    general_words = [
        "BERTHING",
        "BERTHED",
        "RPA BOT",
        "AUTOMATED NOTIFICATION",
        "REMINDER",
    ]

    if any(w in text for w in general_words):
        return {
            "category": "GENERAL",
            "confidence": 0.85,
            "reasoning": "rule: operational/admin vocabulary",
            "method": "RULE",
        }

    # No confident rule match.
    return None


def classify_batch(emails: list[dict]) -> dict[str, dict]:
    """
    Hybrid classification:

    1. Try deterministic rules first.
    2. Send only ambiguous emails to Gemini.
    3. Record whether RULE or GEMINI produced the answer.
    """

    results = {}
    ambiguous = []

    rule_count = 0

    for e in emails:
        r = _rule_classify(e)

        if r is not None:
            results[e["email_id"]] = r
            rule_count += 1
        else:
            ambiguous.append(e)

    gemini_count = 0

    CHUNK = 10

    for i in range(0, len(ambiguous), CHUNK):
        chunk = ambiguous[i:i + CHUNK]

        chunk_results = _gemini_classify_chunk(chunk)

        results.update(chunk_results)
        gemini_count += len(chunk)

    print(
        f"[CLASSIFY] rules={rule_count}, "
        f"Gemini={gemini_count}"
    )

    return results


def _gemini_classify_chunk(chunk: list[dict]) -> dict[str, dict]:
    cache_key = _cache.key(
        "classify",
        *[
            (
                e["email_id"],
                e.get("subject"),
                e.get("body"),
            )
            for e in chunk
        ],
    )

    cached = _cache.get(cache_key)

    if cached is not None:
        print(f"[CACHE] classification cache hit ({len(chunk)} emails)")
        return cached

    emails_block = "\n\n".join(
        f"id: {e['email_id']}\n"
        f"subject: {e.get('subject', '')}\n"
        f"from: {e.get('from', '')}\n"
        f"body: {(e.get('body') or '')[:1500]}"
        for e in chunk
    )

    prompt = _PROMPT.format(
        fewshot=_FEWSHOT,
        cats=" | ".join(CATEGORIES),
        emails_block=emails_block,
    )

    _limiter.wait()

    def _call():
        return client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
            },
        )

    resp = call_with_backoff(_call)

    # ---------------------------------------------------------
    # Token usage logging
    # ---------------------------------------------------------
    usage = getattr(resp, "usage_metadata", None)

    if usage is not None:
        input_tokens = getattr(
            usage,
            "prompt_token_count",
            0,
        )

        output_tokens = getattr(
            usage,
            "candidates_token_count",
            0,
        )

        total_tokens = getattr(
            usage,
            "total_token_count",
            0,
        )

        print(
            f"[TOKENS] input={input_tokens}, "
            f"output={output_tokens}, "
            f"total={total_tokens}"
        )

    try:
        data = json.loads(resp.text)

        out = {}

        for item in data:
            eid = item["id"]

            cat = item.get("category", "GENERAL")

            if cat not in CATEGORIES:
                cat = "GENERAL"

            out[eid] = {
                "category": cat,
                "confidence": item.get("confidence", 0.5),
                "reasoning": item.get("reasoning", ""),
                "method": "GEMINI",
            }

        # Safety fallback
        for e in chunk:
            out.setdefault(
                e["email_id"],
                {
                    "category": "GENERAL",
                    "confidence": 0.0,
                    "reasoning": "parse_fallback",
                    "method": "GEMINI",
                },
            )

        _cache.set(cache_key, out)

        return out

    except Exception as err:

        print(
            f"[CLASSIFY] batch parse failed: {err}"
        )

        return {
            e["email_id"]: {
                "category": "GENERAL",
                "confidence": 0.0,
                "reasoning": "parse_error",
                "method": "GEMINI",
            }
            for e in chunk
        }


def classify(email: dict) -> dict:
    """
    Classify one email.
    """

    r = _rule_classify(email)

    if r is not None:
        return r

    return classify_batch([email])[email["email_id"]]