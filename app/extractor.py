import json
import os
import re
import time

from dotenv import load_dotenv
from google import genai

from ratelimit_cache import RateLimiter, LLMCache, call_with_backoff


load_dotenv()


FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]


FIELD_LABELS = {
    "shipper": [
        "shipper",
        "shipper/exporter",
        "shipper (principal or seller)",
        "exporter",
    ],

    "consignee": [
        "consignee",
        "consignee (non-negotiable)",
        "consignee (收货人)",
    ],

    "notify_party": [
        "notify party/intermediate consignee",
        "notify party / intermediate consignee",
        "notify party",
        "notify",
        "intermediate consignee",
    ],

    "port_of_loading": [
        "load port",
        "port of loading",
        "port of loading (pol)",
        "pol",
        "port of loading (装货港)",
        "loading port",
    ],

    "port_of_discharge": [
        "discharge port",
        "port of discharge",
        "port of discharge (pod)",
        "pod",
        "port of discharge (卸货港)",
        "discharge",
    ],

    "container_count": [
        "container count",
        "total containers",
        "total containers (箱数)",
        "no. of containers or packages",
        "no. of containers",
        "container",
        "containers",
    ],

    "gross_weight_kg": [
        "total gross wt",
        "total gross wt (kgs)",
        "total gross weight",
        "total gross weight (kgs)",
        "gross weight",
        "gross wt",
        "gross wt (kgs)",
        "gross weight (kgs)",
        "gross weight (kg)",
        "gross weight (毛重 kgs)",
        "gross weight (kg) (毛重 kgs)",
    ],
}


# ---------------------------------------------------------------------------
# Labels that indicate the beginning of another field / section.
# ---------------------------------------------------------------------------

ALL_LABELS = sorted(
    {
        label.upper()
        for labels in FIELD_LABELS.values()
        for label in labels
    }
    | {
        "TO THE ORDER OF",
        "VESSEL NAME",
        "VESSEL",
        "OCEAN VESSEL",
        "EXPORT CARRIER",
        "VOYAGE",
        "VOY. NO",
        "COMMODITY",
        "DESCRIPTION OF GOODS",
        "KINDS OF PACKAGES",
        "HS CODE",
        "BOOKING REF",
        "BOOKING NO.",
        "OC NO.",
        "FREIGHT",
        "BILL OF LADING NO.",
        "B/L NO.",
        "POL",
        "POD",
        "CONTAINER NO.",
        "CONTAINER NUMBER",
        "TOTAL GROSS WT",
        "TOTAL GROSS WEIGHT",
    },
    key=len,
    reverse=True,
)


# IMPORTANT:
# The label itself must have word boundaries.
#
# Without this, "POL" can match the POL inside:
#
#     METROPOLITAN
#
# which caused email_059 to extract:
#
#     ITAN ROAD...
#
NEXT_FIELD_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(label) for label in ALL_LABELS)
    + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Rate limiter + disk cache shared across Gemini calls.
# ---------------------------------------------------------------------------

_limiter = RateLimiter(calls_per_minute=12)
_cache = LLMCache()


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()

    # Remove POL/POD markers accidentally captured as part of the value.
    value = re.sub(
        r"^\s*\((?:POL|POD)\)\s*[:：-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    # Remove "Intermediate Consignee:" if accidentally captured.
    value = re.sub(
        r"^\s*/?\s*INTERMEDIATE\s+CONSIGNEE\s*[:：-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    # Remove notify-party label if accidentally captured.
    value = re.sub(
        r"^\s*(?:NOTIFY\s+PARTY|NOTIFY)\s*[:：-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip() or None


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def _extract_table_rows(text: str) -> list[tuple[str, str]]:
    """
    Convert flattened table text into (label, value) pairs.

    Supports:
        Label<TAB>Value
        Label | Value
    """

    rows = []

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if "\t" in line:
            parts = line.split("\t", 1)

        elif "|" in line:
            parts = line.split("|", 1)

        else:
            continue

        if len(parts) != 2:
            continue

        label = parts[0].strip()
        value = parts[1].strip()

        if label and value:
            rows.append((label, value))

    return rows


# ---------------------------------------------------------------------------
# Label matching
# ---------------------------------------------------------------------------

def _label_matches(label: str):
    """
    Match document table labels to the required fields.

    Handles:
    - English labels
    - abbreviations
    - Chinese descriptions
    - labels with extra text in parentheses
    """

    if not label:
        return None

    clean_label = str(label).upper().strip()

    # Normalize spaces and punctuation.
    clean_label = re.sub(r"\s+", " ", clean_label)
    clean_label = clean_label.rstrip(":：=|- ").strip()

    # Remove common parenthetical descriptions.
    base_label = re.sub(
        r"\s*\([^)]*\)",
        "",
        clean_label,
    ).strip()

    # ---------------------------------------------------------
    # Exact known labels
    # ---------------------------------------------------------

    for field, labels in FIELD_LABELS.items():

        for candidate in labels:

            candidate_upper = candidate.upper().strip()

            if clean_label == candidate_upper:
                return field

            if base_label == candidate_upper:
                return field

    # ---------------------------------------------------------
    # Shipping party fields
    # ---------------------------------------------------------

    if base_label.startswith("SHIPPER"):
        return "shipper"

    if base_label.startswith("EXPORTER"):
        return "shipper"

    if base_label.startswith("CONSIGNEE"):
        return "consignee"

    if base_label.startswith("NOTIFY"):
        return "notify_party"

    # ---------------------------------------------------------
    # Ports
    # ---------------------------------------------------------

    if (
        base_label == "LOAD PORT"
        or base_label == "POL"
        or base_label.startswith("PORT OF LOADING")
        or base_label.startswith("LOADING PORT")
    ):
        return "port_of_loading"

    if (
        base_label == "POD"
        or base_label.startswith("PORT OF DISCHARGE")
        or base_label.startswith("DISCHARGE PORT")
    ):
        return "port_of_discharge"

    # ---------------------------------------------------------
    # Container count
    # ---------------------------------------------------------

    if (
        base_label.startswith("CONTAINER COUNT")
        or base_label.startswith("TOTAL CONTAINERS")
        or base_label.startswith("NO. OF CONTAINERS")
        or base_label in {
            "CONTAINER",
            "CONTAINERS",
        }
    ):
        return "container_count"

    # ---------------------------------------------------------
    # Gross weight
    # ---------------------------------------------------------

    if (
        base_label.startswith("GROSS WEIGHT")
        or base_label.startswith("GROSS WT")
        or base_label.startswith("TOTAL GROSS WEIGHT")
        or base_label.startswith("TOTAL GROSS WT")
    ):
        return "gross_weight_kg"

    return None


# ---------------------------------------------------------------------------
# Detect table-like documents
# ---------------------------------------------------------------------------

def _looks_like_table(text: str) -> bool:
    """
    Detect whether the document looks like a flattened table.
    """

    if not text:
        return False

    rows = _extract_table_rows(text)

    matched = 0

    for label, _ in rows:

        if _label_matches(label) is not None:
            matched += 1

    return matched >= 2


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def _extract_from_table(text: str) -> dict:

    result = {
        field: None
        for field in FIELDS
    }

    rows = _extract_table_rows(text)

    for label, value in rows:

        field = _label_matches(label)

        if field is None:
            continue

        value = _clean_value(value)

        if value is None:
            continue

        if field == "container_count":
            value = _extract_container_count(value)

        elif field == "gross_weight_kg":
            value = _extract_gross_weight(value)

        result[field] = value

    return result


# ---------------------------------------------------------------------------
# Build safe field-boundary regex
# ---------------------------------------------------------------------------

def _build_next_field_pattern():

    labels = sorted(
        set(ALL_LABELS),
        key=len,
        reverse=True,
    )

    return (
        r"(?=\n\s*(?:"
        + "|".join(
            r"\b" + re.escape(label) + r"\b"
            for label in labels
        )
        + r")|$)"
    )


NEXT_FIELD_LOOKAHEAD = _build_next_field_pattern()


# ---------------------------------------------------------------------------
# Normal text extraction
# ---------------------------------------------------------------------------

def _extract_labeled_value(
    text: str,
    field: str,
):

    if not text:
        return None

    labels = FIELD_LABELS.get(field, [])

    for label in sorted(labels, key=len, reverse=True):

        # IMPORTANT:
        #
        # Add word boundaries around the label.
        #
        # This prevents:
        #
        #     POL
        #
        # from matching:
        #
        #     METROPOLITAN
        #
        pattern = re.compile(
            r"(?i)"
            r"\b"
            + re.escape(label)
            + r"\b"
            r"\s*(?:[:：=|-]\s*)?"
            r"(.*?)"
            + NEXT_FIELD_LOOKAHEAD,
            re.DOTALL,
        )

        match = pattern.search(text)

        if not match:
            continue

        value = match.group(1)

        value = _clean_value(value)

        if value:
            return value

    # ---------------------------------------------------------
    # Special case:
    #
    # "To the Order of" can be a valid consignee.
    # ---------------------------------------------------------

    if field == "consignee":

        pattern = re.compile(
            r"(?i)"
            r"\b(?:consignee|to the order of)\b"
            r"\s*(?:[:：=|-]\s*)?"
            r"(.*?)"
            + NEXT_FIELD_LOOKAHEAD,
            re.DOTALL,
        )

        match = pattern.search(text)

        if match:

            value = _clean_value(
                match.group(1)
            )

            if value:
                return value

    return None


# ---------------------------------------------------------------------------
# Numeric extraction helpers
# ---------------------------------------------------------------------------

def _extract_container_count(value):
    """
    Extract only the container count.

    Examples:

        12 x 20'FCL       -> 12
        6 x 40'HC         -> 6
        12X20 FCL         -> 12
        12 containers     -> 12
        6                 -> 6
    """

    if value is None:
        return None

    text = str(value).upper()

    text = text.replace(",", "")

    # Prefer explicit container patterns.
    patterns = [
        r"\b(\d+)\s*[X×]\s*\d+",
        r"\b(\d+)\s+CONTAINERS?\b",
        r"\b(\d+)\s+CTNS?\b",
        r"\b(\d+)\s+FCL\b",
        r"\b(\d+)\s*$",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            try:
                return int(match.group(1))
            except ValueError:
                pass

    return None


def _extract_gross_weight(value):
    """
    Extract gross weight.

    Examples:

        243588       -> 243588
        243,588 KGS  -> 243588
        131,322 KG   -> 131322
        216950       -> 216950

    IMPORTANT:
    This function should not interpret the "40" from
    "6 x 40'HC" as gross weight.
    """

    if value is None:
        return None

    text = str(value).upper().strip()

    # Remove commas.
    text = text.replace(",", "")

    # Prefer values explicitly followed by KG/KGS/KILOGRAMS.
    match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(?:KG|KGS|KILOGRAMS?)\b",
        text,
        re.IGNORECASE,
    )

    if match:

        number = match.group(1)

        try:

            number = float(number)

            if number.is_integer():
                return int(number)

            return number

        except ValueError:
            pass

    # If there is no unit, extract a standalone number.
    #
    # But do NOT blindly take the first number if the value
    # contains container dimensions such as:
    #
    #     6 x 40'HC
    #
    # That belongs to container_count, not gross_weight.
    #
    standalone_numbers = re.findall(
        r"\b\d+(?:\.\d+)?\b",
        text,
    )

    if len(standalone_numbers) == 1:

        try:

            number = float(
                standalone_numbers[0]
            )

            if number.is_integer():
                return int(number)

            return number

        except ValueError:
            pass

    return None


# Keep the old helper name for compatibility.
def _extract_number_value(value):

    if value is None:
        return None

    text = str(value).upper()

    # If the value clearly looks like a container description,
    # extract container count.
    if re.search(
        r"\b\d+\s*[X×]\s*\d+",
        text,
    ) or re.search(
        r"\b\d+\s+(?:CONTAINERS?|CTNS?|FCL)\b",
        text,
    ):

        return _extract_container_count(value)

    return _extract_gross_weight(value)


# ---------------------------------------------------------------------------
# Python-first extraction
# ---------------------------------------------------------------------------

def _python_extract(text: str) -> dict:

    result = {
        field: None
        for field in FIELDS
    }

    if not text:
        return result

    # ---------------------------------------------------------
    # Table extraction MUST happen first.
    # ---------------------------------------------------------

    if _looks_like_table(text):

        table_result = _extract_from_table(text)

        if any(
            table_result.get(field) is not None
            for field in FIELDS
        ):

            return table_result

    # ---------------------------------------------------------
    # Normal text extraction
    # ---------------------------------------------------------

    for field in FIELDS:

        result[field] = _extract_labeled_value(
            text,
            field,
        )

    # ---------------------------------------------------------
    # Numeric normalization
    # ---------------------------------------------------------

    result["container_count"] = _extract_container_count(
        result.get("container_count")
    )

    result["gross_weight_kg"] = _extract_gross_weight(
        result.get("gross_weight_kg")
    )

    return result


# ---------------------------------------------------------------------------
# Gemini extraction fallback
# ---------------------------------------------------------------------------

_PROMPT = """
You extract shipping information from a Shipping Instruction (SI)
or Bill of Lading (BL).

Return ONLY valid JSON.

Required fields:

shipper
consignee
notify_party
port_of_loading
port_of_discharge
container_count
gross_weight_kg

Rules:

1. Extract only information actually present in the document.
2. Do not invent missing values.
3. Use null when a value cannot be found.
4. For container_count, return only the numeric container count.
5. For gross_weight_kg, return the numeric gross weight in kg.
6. Preserve company names and addresses accurately.
7. "To the Order of" may be a valid consignee.
8. Do not include unrelated following fields inside a field value.
9. Return exactly one JSON object.

Example:

{
  "shipper": "ABC COMPANY",
  "consignee": "XYZ COMPANY",
  "notify_party": "XYZ COMPANY",
  "port_of_loading": "SINGAPORE",
  "port_of_discharge": "KARACHI, PAKISTAN",
  "container_count": 12,
  "gross_weight_kg": 243588
}
"""


def _gemini_extract(text: str):

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    cache_key = _cache.key(
        "extract",
        text,
    )

    cached = _cache.get(cache_key)

    if cached is not None:
        return cached

    try:

        client = genai.Client(
            api_key=api_key
        )

    except Exception:

        return None

    prompt = (
        _PROMPT
        + "\n\nDOCUMENT:\n"
        + text
    )

    _limiter.wait()

    def _call():

        return client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )

    try:

        response = call_with_backoff(
            _call
        )

    except Exception as e:

        print(
            f"[GEMINI] extraction failed after retries: {e}"
        )

        return None

    try:

        raw = response.text.strip()

        # Remove markdown JSON fences.
        raw = re.sub(
            r"^```json\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        )

        raw = re.sub(
            r"\s*```$",
            "",
            raw,
        )

        data = json.loads(raw)

        result = {
            field: data.get(field)
            for field in FIELDS
        }

        # Normalize numeric fields.
        result["container_count"] = _extract_container_count(
            result.get("container_count")
        )

        result["gross_weight_kg"] = _extract_gross_weight(
            result.get("gross_weight_kg")
        )

        _cache.set(
            cache_key,
            result,
        )

        return result

    except Exception as e:

        print(
            f"[GEMINI] extraction parse failed: {e}"
        )

        return None


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_fields(text: str):

    """
    Main extraction function.

    Strategy:

    1. Python table extraction
    2. Python normal-text extraction
    3. Gemini fallback only if Python did not obtain
       enough information
    """

    if not text or not text.strip():

        return None

    # ---------------------------------------------------------
    # Python first
    # ---------------------------------------------------------

    result = _python_extract(text)

    found = sum(
        1
        for field in FIELDS
        if result.get(field) is not None
    )

    # Avoid Gemini unnecessarily.
    if found >= 2:

        print(
            "[LOCAL] Extraction completed without Gemini"
        )

        return result

    # ---------------------------------------------------------
    # Gemini fallback
    # ---------------------------------------------------------

    print(
        "[LOCAL] Extraction incomplete; trying Gemini"
    )

    gemini_result = _gemini_extract(
        text
    )

    if gemini_result is not None:

        print(
            "[GEMINI] Extraction completed"
        )

        return gemini_result

    # ---------------------------------------------------------
    # Nothing reliable could be extracted.
    # ---------------------------------------------------------

    print(
        "[EXTRACTION] Unable to extract fields"
    )

    return None