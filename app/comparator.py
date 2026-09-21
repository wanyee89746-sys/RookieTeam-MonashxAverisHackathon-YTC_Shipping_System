import re

from extractor import FIELDS


NUMERIC_FIELDS = {
    "container_count",
    "gross_weight_kg",
}

PORT_FIELDS = {
    "port_of_loading",
    "port_of_discharge",
}

PARTY_FIELDS = {
    "shipper",
    "consignee",
    "notify_party",
}


# ---------------------------------------------------------------------------
# Public comparison
# ---------------------------------------------------------------------------

def compare(
    si: dict,
    bl: dict
) -> tuple[bool, list[str]]:

    """
    Compare SI and BL fields.

    Comparison states internally are:

        MATCH
        MISMATCH
        UNKNOWN

    UNKNOWN means that one or both documents do not provide enough
    information to make a reliable comparison.

    Only MISMATCH fields are returned as defects.

    Examples:

        100 vs 100       -> MATCH
        100 vs 101       -> MISMATCH
        None vs 100      -> UNKNOWN
        None vs None     -> UNKNOWN

    Therefore missing information is not automatically reported as
    a document mismatch.
    """

    mismatches = []

    for field in FIELDS:

        result = _compare_field(
            field,
            si.get(field),
            bl.get(field),
        )

        if result == "MISMATCH":
            mismatches.append(field)

    return (
        len(mismatches) > 0,
        sorted(mismatches)
    )


# ---------------------------------------------------------------------------
# Detailed comparison
# ---------------------------------------------------------------------------

def compare_detailed(
    si: dict,
    bl: dict
) -> dict:
    """
    Return the comparison result for every field.

    This is useful for debugging because it distinguishes:

        MATCH
        MISMATCH
        UNKNOWN
    """

    field_results = {}

    for field in FIELDS:

        a = si.get(field)
        b = bl.get(field)

        field_results[field] = {
            "status": _compare_field(field, a, b),
            "si": a,
            "bl": b,
        }

    mismatches = [
        field
        for field, result in field_results.items()
        if result["status"] == "MISMATCH"
    ]

    return {
        "has_defect": len(mismatches) > 0,
        "defect_fields": sorted(mismatches),
        "field_results": field_results,
    }


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------

def _compare_field(
    field: str,
    a,
    b,
) -> str:

    # ---------------------------------------------------------
    # Missing values
    # ---------------------------------------------------------

    if _is_missing(a) or _is_missing(b):
        return "UNKNOWN"

    # ---------------------------------------------------------
    # Numeric fields
    # ---------------------------------------------------------

    if field in NUMERIC_FIELDS:
        return _compare_numeric(a, b)

    # ---------------------------------------------------------
    # Port fields
    # ---------------------------------------------------------

    if field in PORT_FIELDS:
        return _compare_port(a, b)

    # ---------------------------------------------------------
    # Party fields
    # ---------------------------------------------------------

    if field in PARTY_FIELDS:
        return _compare_party(a, b)

    # ---------------------------------------------------------
    # Generic fallback
    # ---------------------------------------------------------

    return (
        "MATCH"
        if _normalize_text(a) == _normalize_text(b)
        else "MISMATCH"
    )


# ---------------------------------------------------------------------------
# Missing detection
# ---------------------------------------------------------------------------

BLANK_TOKENS = {
    "",
    "???",
    "___",
    "_______",
    "TBA",
    "TBC",
    "N/A",
    "NA",
    "NULL",
    "NONE",
    "____MT",
}


def _is_missing(value) -> bool:

    if value is None:
        return True

    text = str(value).strip().upper()

    return text in BLANK_TOKENS


# ---------------------------------------------------------------------------
# Numeric comparison
# ---------------------------------------------------------------------------

def _compare_numeric(a, b) -> str:

    try:

        a_num = float(str(a).replace(",", "").strip())
        b_num = float(str(b).replace(",", "").strip())

    except (ValueError, TypeError):

        return "MISMATCH"

    if a_num == b_num:
        return "MATCH"

    return "MISMATCH"


# ---------------------------------------------------------------------------
# Party comparison
# ---------------------------------------------------------------------------

def _compare_party(a, b) -> str:

    a_norm = _normalize_party(a)
    b_norm = _normalize_party(b)

    if a_norm is None or b_norm is None:
        return "UNKNOWN"

    if a_norm == b_norm:
        return "MATCH"

    return "MISMATCH"


def _normalize_party(value):

    if _is_missing(value):
        return None

    text = str(value).upper()

    # Remove common field labels.
    text = re.sub(
        r"\b(?:SHIPPER|EXPORTER|CONSIGNEE)\s*[:：-]?\s*",
        " ",
        text,
    )

    text = re.sub(
        r"\b(?:NOTIFY\s+PARTY|NOTIFY)\s*[:：-]?\s*",
        " ",
        text,
    )

    text = re.sub(
        r"/?\s*INTERMEDIATE\s+CONSIGNEE\s*[:：-]?\s*",
        " ",
        text,
    )

    # Remove document descriptors at the beginning.
    text = re.sub(
        r"^\s*\([^)]*\)\s*[:：-]?\s*",
        "",
        text,
    )

    # Normalize line/separator structure.
    text = re.sub(r"[|;]+", "\n", text)
    text = re.sub(r"\r\n?", "\n", text)

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
    ]

    # Ignore descriptor-only lines.
    while lines and re.fullmatch(r"\([^)]*\)", lines[0]):
        lines.pop(0)

    if not lines:
        return None

    # ---------------------------------------------------------
    # IMPORTANT:
    #
    # Do NOT remove "ON BEHALF OF ..." automatically.
    #
    # It can represent meaningful business information.
    #
    # Therefore:
    #
    # APRIL FINE PAPER TRADING
    #
    # and
    #
    # APRIL FINE PAPER TRADING
    # ON BEHALF OF VITAL SOLUTIONS PTE LTD
    #
    # are not automatically treated as identical.
    # ---------------------------------------------------------

    text = " ".join(lines)

    text = re.sub(r"\s+", " ", text).strip()

    # Whitespace should not affect company-name comparison.
    text = re.sub(r"\s+", "", text)

    return text or None


# ---------------------------------------------------------------------------
# Port comparison
# ---------------------------------------------------------------------------

def _compare_port(a, b) -> str:

    a_port = _parse_port(a)
    b_port = _parse_port(b)

    if a_port is None or b_port is None:
        return "UNKNOWN"

    # ---------------------------------------------------------
    # If both sides contain a LOCODE and the codes differ,
    # they are definitely different ports.
    # ---------------------------------------------------------

    if (
        a_port["code"] is not None
        and b_port["code"] is not None
        and a_port["code"] != b_port["code"]
    ):
        return "MISMATCH"

    # ---------------------------------------------------------
    # Compare the actual place text.
    #
    # This is important because the same five-character code
    # must NOT automatically mean the same port.
    #
    # Example:
    #
    # MOMBASA, KENYA (KEMBA)
    # TUTICORIN, INDIA (KEMBA)
    #
    # Same code, different place -> MISMATCH.
    # ---------------------------------------------------------

    a_name = a_port["name"]
    b_name = b_port["name"]

    if a_name == b_name:
        return "MATCH"

    # If one side is simply a more detailed version of the same
    # place, allow it to match.
    if _port_names_compatible(a_name, b_name):
        return "MATCH"

    return "MISMATCH"


def _parse_port(value):

    if _is_missing(value):
        return None

    text = str(value).upper().strip()

    text = re.sub(
        r"[|;]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if not text:
        return None

    # Find a trailing or embedded UN/LOCODE.
    code_match = re.search(
        r"\(([A-Z]{5})\)",
        text,
    )

    code = (
        code_match.group(1)
        if code_match
        else None
    )

    # Remove only the LOCODE from the name.
    name = re.sub(
        r"\s*\([A-Z]{5}\)\s*$",
        "",
        text,
    ).strip()

    # Remove a leading POL/POD marker if it survived extraction.
    name = re.sub(
        r"^\s*\((?:POL|POD)\)\s*[:：-]?\s*",
        "",
        name,
        flags=re.IGNORECASE,
    )

    name = re.sub(
        r"\s+",
        " ",
        name,
    ).strip()

    if not name:
        return None

    return {
        "name": _normalize_port_name(name),
        "code": code,
    }


def _normalize_port_name(value):

    text = str(value).upper().strip()

    # Normalize punctuation/separators.
    text = re.sub(
        r"\s*,\s*",
        ", ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    # Normalize common slash/spacing variation.
    text = re.sub(
        r"\s*/\s*",
        "/",
        text,
    )

    return text.strip(" ,")


def _port_names_compatible(a, b) -> bool:

    if a == b:
        return True

    # Exact normalized containment is allowed only when the
    # shorter value represents the same complete place name.
    #
    # Example:
    # SINGAPORE
    # SINGAPORE, SINGAPORE
    #
    # This does NOT make:
    # MOMBASA, KENYA
    # TUTICORIN, INDIA
    # compatible.
    a_parts = {
        part.strip()
        for part in a.split(",")
        if part.strip()
    }

    b_parts = {
        part.strip()
        for part in b.split(",")
        if part.strip()
    }

    if not a_parts or not b_parts:
        return False

    # One side may contain additional location detail, but every
    # component from the shorter side must be present on the
    # longer side.
    if a_parts.issubset(b_parts):
        return True

    if b_parts.issubset(a_parts):
        return True

    # Handle simple "CITY COUNTRY" versus "CITY, COUNTRY".
    a_space = re.sub(r"[,\s]+", " ", a).strip()
    b_space = re.sub(r"[,\s]+", " ", b).strip()

    return (
        a_space == b_space
    )


# ---------------------------------------------------------------------------
# Generic text normalization
# ---------------------------------------------------------------------------

def _normalize_text(value):

    if _is_missing(value):
        return None

    text = str(value).upper().strip()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.replace(" ", "")