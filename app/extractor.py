import json
import os
import re

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
        "shipper/exporter",
        "shipper (principal or seller)",
        "shipper",
        "exporter",
    ],
    "consignee": [
        "consignee (non-negotiable)",
        "consignee (收货人)",
        "consignee",
    ],
    "notify_party": [
        "notify party/intermediate consignee",
        "notify party / intermediate consignee",
        "notify party",
        "notify",
        "intermediate consignee",
    ],
    "port_of_loading": [
        "port of loading (pol)",
        "port of loading (装货港)",
        "port of loading",
        "loading port",
        "load port",
        "pol",
    ],
    "port_of_discharge": [
        "port of discharge (pod)",
        "port of discharge (卸货港)",
        "port of discharge",
        "discharge port",
        "discharge",
        "pod",
    ],
    "container_count": [
        "no. of containers or packages",
        "no. of containers",
        "container count",
        "total containers",
        "total containers (箱数)",
        "containers",
        "container",
    ],
    "gross_weight_kg": [
        "gross weight (kg)",
        "gross weight (kgs)",
        "gross weight毛重(kgs)",
        "gross weight (毛重 kgs)",
        "gross weight (kg) (毛重 kgs)",
        "gross wt (kgs)",
        "gross wt (kg)",
        "gross wt",
        "total gross weight",
        "total gross wt (kgs)",
        "total gross wt",
        "gross weight",
    ],
}


# Labels that should terminate a value when parsing ordinary text.
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
        "BOOKING REFERENCE",
        "BOOKING NO.",
        "BOOKING NO",
        "OC NO.",
        "OC NO",
        "FREIGHT",
        "BILL OF LADING NO.",
        "BILL OF LADING NO",
        "B/L NO.",
        "B/L NO",
        "BL NO.",
        "BL NO",
        "CONTAINER NO.",
        "CONTAINER NUMBER",
        "TOTAL GROSS WT",
        "TOTAL GROSS WEIGHT",
        "NET WEIGHT",
    },
    key=len,
    reverse=True,
)


BLANK_TOKENS = {
    "",
    "N/A",
    "NA",
    "NIL",
    "NONE",
    "NULL",
    "TBA",
    "TBC",
    "???",
    "___",
    "____",
    "_____",
    "______",
    "_______",
    "____MT",
    "_____MT",
    "______MT",
    "_______MT",
}


_limiter = RateLimiter(calls_per_minute=12)
_cache = LLMCache()


def is_missing_value(value) -> bool:
    """
    Return True when a value is explicitly blank or a placeholder.
    """
    if value is None:
        return True

    text = str(value).strip().upper()

    if text in BLANK_TOKENS:
        return True

    # Placeholder-only values such as ______ or ____MT.
    if re.fullmatch(r"_+\s*(?:MT|MTS)?", text):
        return True

    if re.fullmatch(r"\?+", text):
        return True

    return False


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None

    value = str(value).strip()

    if is_missing_value(value):
        return None

    # Remove table/field prefixes accidentally included in a value.
    value = re.sub(
        r"^\s*\((?:POL|POD)\)\s*[:：-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^\s*/?\s*INTERMEDIATE\s+CONSIGNEE\s*[:：-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^\s*(?:NOTIFY\s+PARTY|NOTIFY)\s*[:：-]?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip() or None


def _normalize_label(label: str) -> str:
    text = str(label).upper().strip()
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(":：=|- ").strip()
    return text


def _label_matches(label: str):
    """
    Convert a document label into one of our internal fields.

    Important:
    'Notify Party/Intermediate Consignee' is checked as notify_party
    before any generic 'consignee' matching.
    """
    if not label:
        return None

    clean_label = _normalize_label(label)

    # IMPORTANT: notify must be checked before consignee.
    for candidate in FIELD_LABELS["notify_party"]:
        if clean_label == _normalize_label(candidate):
            return "notify_party"

    # Exact matches for all fields.
    for field, labels in FIELD_LABELS.items():
        for candidate in labels:
            if clean_label == _normalize_label(candidate):
                return field

    # Remove parenthetical language for variants such as:
    # Consignee (Non-Negotiable)
    # Shipper (Principal or Seller)
    base_label = re.sub(r"\s*\([^)]*\)", "", clean_label).strip()

    # Again, notify first.
    if (
        base_label.startswith("NOTIFY PARTY")
        or base_label.startswith("NOTIFY")
        or base_label == "INTERMEDIATE CONSIGNEE"
    ):
        return "notify_party"

    if base_label.startswith("SHIPPER"):
        return "shipper"

    if base_label.startswith("EXPORTER"):
        return "shipper"

    if base_label.startswith("CONSIGNEE"):
        return "consignee"

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
        or base_label == "DISCHARGE"
    ):
        return "port_of_discharge"

    if (
        base_label.startswith("CONTAINER COUNT")
        or base_label.startswith("TOTAL CONTAINERS")
        or base_label.startswith("NO. OF CONTAINERS")
        or base_label in {"CONTAINER", "CONTAINERS"}
    ):
        return "container_count"

    if (
        base_label.startswith("GROSS WEIGHT")
        or base_label.startswith("GROSS WT")
        or base_label.startswith("TOTAL GROSS WEIGHT")
        or base_label.startswith("TOTAL GROSS WT")
    ):
        return "gross_weight_kg"

    return None


def _extract_table_rows(text: str) -> list[tuple[str, str]]:
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

        if label:
            rows.append((label, value))

    return rows


def _looks_like_table(text: str) -> bool:
    if not text:
        return False

    rows = _extract_table_rows(text)

    matched = sum(
        1
        for label, _ in rows
        if _label_matches(label) is not None
    )

    return matched >= 2


def _extract_from_table(text: str) -> dict:
    result = {field: None for field in FIELDS}

    for label, value in _extract_table_rows(text):
        field = _label_matches(label)

        if field is None:
            continue

        value = _clean_value(value)

        # Empty table cells are genuinely missing.
        if value is None:
            continue

        if field == "container_count":
            value = _extract_container_count(value)

        elif field == "gross_weight_kg":
            value = _extract_gross_weight(value)

        if value is not None:
            result[field] = value

    return result


def _split_lines(text: str) -> list[str]:
    """
    Normalize document text into logical lines.

    Keeps the line structure because it is important for detecting
    blank fields without consuming the following field.
    """
    if not text:
        return []

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()

        if line:
            lines.append(line)

    return lines


def _parse_label_value_line(line: str):
    """
    Return (field, value, explicit_blank) if the line starts with
    one of our known labels.

    Examples:

        CONSIGNEE: ABC
        CONSIGNEE:
        Notify Party/Intermediate Consignee: ABC
        Port of Loading (POL): SINGAPORE
        Gross Weight (KG): 123 KG
    """
    if not line:
        return None

    # Longest labels first.
    labels_by_length = sorted(
        (
            (field, label)
            for field, labels in FIELD_LABELS.items()
            for label in labels
        ),
        key=lambda item: len(item[1]),
        reverse=True,
    )

    for field, label in labels_by_length:
        pattern = re.compile(
            r"^\s*"
            + re.escape(label)
            + r"\s*(?:[:：=|-]\s*)?(.*)$",
            re.IGNORECASE,
        )

        match = pattern.match(line)

        if not match:
            continue

        raw_value = match.group(1).strip()

        if not raw_value:
            return field, None, True

        cleaned = _clean_value(raw_value)

        if cleaned is None:
            return field, None, True

        return field, cleaned, False

    return None


def _extract_to_the_order_of(line: str):
    """
    Handle:

        To the Order of ABC
        To the Order of: ABC
    """
    match = re.match(
        r"^\s*TO\s+THE\s+ORDER\s+OF\s*(?:[:：=-]\s*)?(.*)$",
        line,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    value = _clean_value(match.group(1))

    if value is None:
        return "consignee", None, True

    return "consignee", value, False


def _extract_line_based(text: str) -> tuple[dict, dict]:
    """
    Extract fields from individual logical lines and standalone labels.

    Supports both:

        Shipper: ABC COMPANY

    and:

        Shipper
        ABC COMPANY
        ADDRESS...

    A field is marked explicitly missing only when:
      1. the document contains the field label, and
      2. no valid value is found for that field.
    """
    result = {field: None for field in FIELDS}
    explicit_missing = {field: False for field in FIELDS}

    lines = _split_lines(text)

    # Map each line to a field when the line is a standalone label.
    standalone_labels = []

    for index, line in enumerate(lines):
        parsed = _extract_to_the_order_of(line)

        if parsed is not None:
            standalone_labels.append((index, parsed[0], parsed[1], parsed[2]))
            continue

        parsed = _parse_label_value_line(line)

        if parsed is not None:
            standalone_labels.append((index, parsed[0], parsed[1], parsed[2]))

    # First pass: normal inline label/value extraction.
    for index, field, value, missing in standalone_labels:
        if missing:
            explicit_missing[field] = True
            continue

        if field == "container_count":
            value = _extract_container_count(value)
        elif field == "gross_weight_kg":
            value = _extract_gross_weight(value)

        if value is not None:
            result[field] = value
            explicit_missing[field] = False

    # Second pass: standalone labels followed by value lines.
    for index, field, value, missing in standalone_labels:

        # Already got a valid value from inline extraction.
        if result[field] is not None:
            continue

        # Only process labels with no inline value.
        if not missing:
            continue

        # Look at the following lines until another recognized field
        # label is reached.
        following = []

        for next_index in range(index + 1, len(lines)):
            next_line = lines[next_index]

            next_parsed = _extract_to_the_order_of(next_line)

            if next_parsed is None:
                next_parsed = _parse_label_value_line(next_line)

            if next_parsed is not None:
                break

            # Stop at obvious document/table headers.
            upper = next_line.upper().strip()

            if upper in {
                "CONTAINER NO.",
                "CONTAINER NUMBER",
                "DESCRIPTION",
                "GROSS WEIGHT (KG)",
                "GROSS WEIGHT (KGS)",
                "TOTAL GROSS WT",
                "TOTAL GROSS WEIGHT",
                "OCEAN VESSEL",
                "VESSEL",
                "EXPORT CARRIER",
            }:
                break

            following.append(next_line)

            # For non-party fields, normally only the immediate next
            # logical line should be considered.
            if field not in {"shipper", "consignee", "notify_party"}:
                break

        if not following:
            continue

        if field in {"shipper", "consignee", "notify_party"}:
            # Party values can span multiple address lines.
            value = following[0]
        else:
            value = following[0]

        value = _clean_value(value)

        if field == "container_count":
            value = _extract_container_count(value)
        elif field == "gross_weight_kg":
            value = _extract_gross_weight(value)

        if value is not None:
            result[field] = value
            explicit_missing[field] = False

    # Third pass: existing multiline-party fallback.
    #
    # This is kept as a safety net for documents whose party structure
    # is slightly different from the standard standalone-label format.
    for field in ("shipper", "consignee", "notify_party"):
        if result[field] is None:
            fallback = _extract_multiline_party(text, field)

            if fallback is not None:
                result[field] = fallback
                explicit_missing[field] = False

    # Any field with a valid value is never considered explicitly missing.
    for field in FIELDS:
        if result[field] is not None:
            explicit_missing[field] = False

    return result, explicit_missing


def _extract_multiline_party(text: str, field: str):
    """
    Extract party values while preserving only the party/company
    portion and stopping before the next known field.

    This is mainly a fallback for formats where the party address
    is on following lines.
    """
    if not text:
        return None

    lines = _split_lines(text)

    target_labels = FIELD_LABELS.get(field, [])

    for index, line in enumerate(lines):
        matched = False

        for label in target_labels:
            if re.match(
                r"^\s*" + re.escape(label) + r"\s*(?:[:：=|-]\s*)?",
                line,
                flags=re.IGNORECASE,
            ):
                matched = True
                break

        if not matched:
            if field == "consignee":
                to_order = _extract_to_the_order_of(line)
                if to_order is not None:
                    return to_order[1]
            continue

        # Remove label from current line.
        value = re.sub(
            r"^\s*(?:"
            + "|".join(
                re.escape(label)
                for label in sorted(target_labels, key=len, reverse=True)
            )
            + r")\s*(?:[:：=|-]\s*)?",
            "",
            line,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        value = _clean_value(value)

        if value:
            return value

        # Explicitly blank field.
        return None

    return None


def _extract_container_count(value):
    if value is None:
        return None

    text = str(value).upper().replace(",", "").strip()

    patterns = [
        r"\b(\d+)\s*[X×]\s*\d+",
        r"\b(\d+)\s+CONTAINERS?\b",
        r"\b(\d+)\s+CTNS?\b",
        r"\b(\d+)\s+FCL\b",
        r"^\s*(\d+)\s*$",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            try:
                return int(match.group(1))
            except (ValueError, TypeError):
                pass

    return None


def _extract_gross_weight(value):
    if value is None:
        return None

    text = str(value).upper().strip()

    if is_missing_value(text):
        return None

    text = text.replace(",", "")

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

    standalone_numbers = re.findall(
        r"\b\d+(?:\.\d+)?\b",
        text,
    )

    if len(standalone_numbers) == 1:
        try:
            number = float(standalone_numbers[0])

            if number.is_integer():
                return int(number)

            return number

        except ValueError:
            pass

    return None


def _python_extract(text: str) -> tuple[dict, dict]:
    """
    Local extraction.

    Returns:
        fields
        explicit_missing
    """
    result = {field: None for field in FIELDS}
    explicit_missing = {field: False for field in FIELDS}

    if not text:
        return result, explicit_missing

    # First use structured table extraction.
    if _looks_like_table(text):
        table_result = _extract_from_table(text)

        # Also run line parsing because a table can contain explicit
        # blank fields that table extraction naturally skips.
        line_result, line_missing = _extract_line_based(text)

        for field in FIELDS:
            if table_result.get(field) is not None:
                result[field] = table_result[field]
            elif line_result.get(field) is not None:
                result[field] = line_result[field]

            # Only keep explicit_missing=True when there is no valid
            # extracted value.
            if result[field] is not None:
                explicit_missing[field] = False
            else:
                explicit_missing[field] = line_missing[field]

        return result, explicit_missing

    result, explicit_missing = _extract_line_based(text)

    # Party fallback for formats that are not cleanly line-oriented.
    for field in ("shipper", "consignee", "notify_party"):
        if result[field] is None and not explicit_missing[field]:
            fallback = _extract_multiline_party(text, field)

            if fallback is not None:
                result[field] = fallback

    return result, explicit_missing


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
4. An explicitly blank field such as "CONSIGNEE:" must be null.
5. Do not use the value from the next field when the current field is blank.
6. "To the Order of" is a valid consignee.
7. "Notify Party/Intermediate Consignee" belongs to notify_party,
   not consignee.
8. For container_count, return only the numeric container count.
9. For gross_weight_kg, return the numeric gross weight in kg.
10. Preserve company names accurately.
11. Preserve port name and country accurately.
12. A port LOCODE in parentheses is additional information and must
    not replace a conflicting port name or country.
13. Do not include unrelated following fields inside a field value.
14. Return exactly one JSON object.

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

    cache_key = _cache.key("extract", text)
    cached = _cache.get(cache_key)

    if cached is not None:
        return cached

    try:
        client = genai.Client(api_key=api_key)
    except Exception:
        return None

    prompt = _PROMPT + "\n\nDOCUMENT:\n" + text

    _limiter.wait()

    def _call():
        return client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )

    try:
        response = call_with_backoff(_call)
    except Exception as e:
        print(f"[GEMINI] extraction failed after retries: {e}")
        return None

    try:
        raw = response.text.strip()

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

        for field in ("shipper", "consignee", "notify_party",
                      "port_of_loading", "port_of_discharge"):
            result[field] = _clean_value(result[field])

        result["container_count"] = _extract_container_count(
            result.get("container_count")
        )

        result["gross_weight_kg"] = _extract_gross_weight(
            result.get("gross_weight_kg")
        )

        _cache.set(cache_key, result)

        return result

    except Exception as e:
        print(f"[GEMINI] extraction parse failed: {e}")
        return None


def _has_suspicious_port_extraction(fields: dict, text: str) -> bool:
    """
    Detect cases where local extraction probably captured a bad port
    value and Gemini should get a chance to correct it.
    """
    if not text:
        return False

    for field in ("port_of_loading", "port_of_discharge"):
        value = fields.get(field)

        if value is None:
            continue

        text_value = str(value).upper()

        # Port values should generally contain a recognizable
        # location-like string, not an unrelated field label.
        bad_fragments = [
            "VESSEL",
            "VOYAGE",
            "CONTAINER",
            "GROSS WEIGHT",
            "BOOKING",
            "FREIGHT",
        ]

        if any(fragment in text_value for fragment in bad_fragments):
            return True

    return False


def extract_fields(text: str):
    """
    Main extraction function.

    Strategy:
    1. Local line/table extraction.
    2. Gemini fallback when local extraction is too incomplete or
       suspicious.
    """
    if not text or not text.strip():
        return None

    result, explicit_missing = _python_extract(text)

    found = sum(
        1
        for field in FIELDS
        if result.get(field) is not None
    )

    suspicious_port = _has_suspicious_port_extraction(
        result,
        text,
    )

    # Keep explicit missing information available to escalation.
    # The current pipeline only receives the returned dict, so attach
    # it as metadata without changing the normal field interface.
    result["_explicit_missing"] = explicit_missing

    if found >= 2 and not suspicious_port:
        print("[LOCAL] Extraction completed without Gemini")
        return result

    print("[LOCAL] Extraction incomplete; trying Gemini")

    gemini_result = _gemini_extract(text)

    if gemini_result is not None:
        # Preserve local explicit-missing information.
        gemini_result["_explicit_missing"] = explicit_missing

        print("[GEMINI] Extraction completed")
        return gemini_result

    print("[EXTRACTION] Unable to extract fields")

    # Local result is still useful when Gemini is unavailable.
    if found > 0:
        return result

    return None