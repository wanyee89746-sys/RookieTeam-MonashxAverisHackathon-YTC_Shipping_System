import json
import os
import re
import time

from dotenv import load_dotenv
from google import genai


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
        "notify party",
        "notify",
        "notification party",
    ],
    "port_of_loading": [
        "load port",
        "port of loading",
        "port of loading (装货港)",
        "loading port",
    ],
    "port_of_discharge": [
        "pod",
        "port of discharge",
        "port of discharge (卸货港)",
        "discharge port",
    ],
    "container_count": [
        "container count",
        "total containers",
        "total containers (箱数)",
        "container",
        "containers",
    ],
    "gross_weight_kg": [
        "gross weight",
        "gross wt",
        "gross wt (kgs)",
        "gross weight (kgs)",
        "gross weight (kg)",
        "gross weight (毛重 kgs)",
        "gross weight (kg) (毛重 kgs)",
    ],
}


ALL_LABELS = sorted(
    {
        label.upper()
        for labels in FIELD_LABELS.values()
        for label in labels
    },
    key=len,
    reverse=True,
)


NEXT_FIELD_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(label) for label in ALL_LABELS)
    + r")\b",
    re.IGNORECASE,
)


def _clean_value(value):
    if value is None:
        return None

    value = str(value)

    # Remove accidental table separators.
    value = value.replace("\r", " ")
    value = re.sub(r"\s+", " ", value)

    # Remove leading/trailing separators.
    value = value.strip(" \t:|-")

    return value.strip() or None


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


def _label_matches(label: str):
    """
    Match document table labels to the required fields.

    Handles English labels, abbreviations, Chinese descriptions,
    and labels with extra text in parentheses.
    """

    if not label:
        return None

    clean_label = str(label).upper().strip()

    # Normalize spaces and punctuation.
    clean_label = re.sub(r"\s+", " ", clean_label)
    clean_label = clean_label.rstrip(":：=|- ").strip()

    # Remove common parenthetical descriptions so that:
    #
    # Shipper (Principal or Seller) (发货人)
    # Gross Wt (kgs) (毛重 KGS)
    #
    # can still be matched reliably.
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
    ):
        return "gross_weight_kg"

    return None

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


def _extract_from_table(text: str) -> dict:
    """
    Extract fields from flattened table rows.

    IMPORTANT:
    Each table row is treated independently.

    Example:

        Consignee | AL GURG STATIONERY LLC
        Notify Party | AL GURG STATIONERY LLC
        Load Port | SINGAPORE

    The consignee value therefore cannot accidentally consume
    the following Notify Party / Load Port rows.
    """

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
            value = _extract_number_value(value)

        elif field == "gross_weight_kg":
            value = _extract_number_value(value)

        result[field] = value

    return result


def _extract_labeled_value(
    text: str,
    field: str,
):
    """
    Extract a value from normal text where the label and value
    may appear on the same line or where the next field label
    indicates the end of the current value.
    """

    if not text:
        return None

    labels = FIELD_LABELS.get(field, [])

    for label in sorted(labels, key=len, reverse=True):

        pattern = re.compile(
            r"(?i)"
            + re.escape(label)
            + r"\s*(?:[:：=|-]\s*)?"
            + r"(.*?)"
            + r"(?=\n\s*(?:"
            + "|".join(
                re.escape(x)
                for x in ALL_LABELS
            )
            + r")\b|$)",
            re.DOTALL,
        )

        match = pattern.search(text)

        if not match:
            continue

        value = match.group(1)

        value = _clean_value(value)

        if value:
            return value

    # Special case for "To the Order of".
    if field == "consignee":
        pattern = re.compile(
            r"(?i)"
            r"(?:consignee|to the order of)"
            r"\s*(?:[:：=|-]\s*)?"
            r"(.*?)"
            r"(?=\n\s*(?:"
            + "|".join(
                re.escape(x)
                for x in ALL_LABELS
            )
            + r")\b|$)",
            re.DOTALL,
        )

        match = pattern.search(text)

        if match:
            value = _clean_value(match.group(1))

            if value:
                return value

    return None


def _extract_number_value(value):
    """
    Extract numeric values for:

        container_count
        gross_weight_kg
    """

    if value is None:
        return None

    text = str(value).upper()

    # Remove commas from numbers.
    text = text.replace(",", "")

    # Container examples:
    # 12 x 20'FCL
    # 12X20 FCL
    # 12 containers
    # 12
    #
    # We only need the container count.
    match = re.search(
        r"\b(\d+)\s*(?:X\b|CONTAINERS?\b|CTNS?\b|FCL\b)?",
        text,
    )

    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    # Gross weight examples:
    # 243588
    # 243,588 KGS
    # 243588 KG
    match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(?:KG|KGS|KILOGRAMS?)?\b",
        text,
    )

    if match:
        number = match.group(1)

        try:
            value = float(number)

            if value.is_integer():
                return int(value)

            return value

        except ValueError:
            pass

    return None


def _python_extract(text: str) -> dict:
    """
    Python-first extraction.

    Table documents are handled by the table parser first.
    Generic label parsing is only used for non-table documents.
    """

    result = {
        field: None
        for field in FIELDS
    }

    if not text:
        return result

    # ---------------------------------------------------------
    # IMPORTANT:
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

    result["container_count"] = _extract_number_value(
        result.get("container_count")
    )

    result["gross_weight_kg"] = _extract_number_value(
        result.get("gross_weight_kg")
    )

    return result


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
7. "To the Order of" may be a valid consignee and should not be
   treated as an extraction failure.
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
    """
    Gemini fallback for documents that Python cannot reliably parse.
    """

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

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

    max_retries = 5

    for attempt in range(max_retries):

        try:

            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
            )

            raw = response.text.strip()

            # Remove markdown JSON fences if Gemini returns them.
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
            result["container_count"] = _extract_number_value(
                result.get("container_count")
            )

            result["gross_weight_kg"] = _extract_number_value(
                result.get("gross_weight_kg")
            )

            return result

        except Exception as e:

            error_text = str(e)

            # Retry temporary quota/network errors.
            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
                or "503" in error_text
                or "UNAVAILABLE" in error_text
                or "DEADLINE" in error_text
                or "getaddrinfo" in error_text
            ):

                wait_seconds = 10 * (attempt + 1)

                print(
                    f"[GEMINI] retry {attempt + 1}/{max_retries} "
                    f"after {wait_seconds}s: {error_text}"
                )

                time.sleep(wait_seconds)

                continue

            print(
                f"[GEMINI] extraction failed: {error_text}"
            )

            return None

    return None


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

    # Count how many required fields were found.
    found = sum(
        1
        for field in FIELDS
        if result.get(field) is not None
    )

    # For normal shipping documents, 2+ extracted fields is
    # usually enough to trust the local parser.
    #
    # This is especially important for the 520-email dataset:
    # do NOT call Gemini unnecessarily.
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

    gemini_result = _gemini_extract(text)

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