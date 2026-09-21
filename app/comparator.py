import re

from extractor import FIELDS, is_missing_value


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


def compare(si: dict, bl: dict) -> tuple[bool, list[str]]:
    """
    Compare SI and BL fields.

    Returns:
        (has_defect, sorted_defect_fields)
    """
    detailed = compare_detailed(si, bl)

    return (
        detailed["has_defect"],
        detailed["defect_fields"],
    )


def compare_detailed(si: dict, bl: dict) -> dict:
    """
    Detailed comparison.

    Returns a dictionary because pipeline.py expects:

        detailed["has_defect"]
        detailed["defect_fields"]
        detailed["field_results"]

    field_results[field] is one of:

        MATCH
        MISMATCH
        UNKNOWN
    """
    mismatches = []
    field_results = {}

    for field in FIELDS:
        result = _compare_field(
            field,
            si.get(field),
            bl.get(field),
        )

        field_results[field] = result

        if result == "MISMATCH":
            mismatches.append(field)

    return {
        "has_defect": len(mismatches) > 0,
        "defect_fields": sorted(mismatches),
        "field_results": field_results,
    }


def _compare_field(field: str, a, b) -> str:
    if field in NUMERIC_FIELDS:
        return _compare_numeric(field, a, b)

    if field in PORT_FIELDS:
        return _compare_port(a, b)

    if field in PARTY_FIELDS:
        return _compare_party(a, b)

    return _compare_text(a, b)


def _is_missing(value) -> bool:
    return is_missing_value(value)


def _compare_numeric(field: str, a, b) -> str:
    a_missing = _is_missing(a)
    b_missing = _is_missing(b)

    if a_missing or b_missing:
        return "UNKNOWN"

    try:
        if field == "gross_weight_kg":
            a_num = float(a)
            b_num = float(b)

            return "MATCH" if a_num == b_num else "MISMATCH"

        a_num = int(float(a))
        b_num = int(float(b))

        return "MATCH" if a_num == b_num else "MISMATCH"

    except (ValueError, TypeError):
        return "MISMATCH"


def _normalize_party(value):
    """
    Normalize a party/company value for comparison.

    Example:

        ASIA PACIFIC PAPERBOARD TRADING PTE LTD
        |
        80 RAFFLES PLACE, #50-01 UOB PLAZA 1
        |
        SINGAPORE

    becomes:

        ASIA PACIFIC PAPERBOARD TRADING PTE LTD

    This allows the SI and BL to match when the SI contains the
    address but the BL only contains the company name.

    We do NOT use substring matching between different company names.
    """

    if _is_missing(value):
        return None

    text = str(value).upper().strip()

    # Remove known field prefixes.
    text = re.sub(
        r"^\s*(?:SHIPPER|EXPORTER)\s*[:：-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^\s*CONSIGNEE\s*[:：-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^\s*(?:NOTIFY\s+PARTY|NOTIFY)\s*[:：-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^\s*INTERMEDIATE\s+CONSIGNEE\s*[:：-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove labels such as:
    #
    # (Principal or Seller):
    # (Non-Negotiable):
    #
    text = re.sub(
        r"^\s*\([^)]*\)\s*[:：-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Normalize separators.
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # A pipe or semicolon usually separates the company name from
    # the address in the extracted spreadsheet text.
    text = re.sub(r"[|;]+", "\n", text)

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
    ]

    if not lines:
        return None

    company = lines[0]

    # Remove any field prefix that survived previous cleanup.
    company = re.sub(
        r"^\s*(?:"
        r"SHIPPER"
        r"|EXPORTER"
        r"|CONSIGNEE"
        r"|NOTIFY\s+PARTY"
        r"|NOTIFY"
        r")\s*[:：-]?\s*",
        "",
        company,
        flags=re.IGNORECASE,
    )

    # Remove parenthetical label prefix.
    company = re.sub(
        r"^\s*\([^)]*\)\s*[:：-]?\s*",
        "",
        company,
    )

    # Normalize whitespace.
    company = re.sub(r"\s+", " ", company).strip()

    # Remove trailing punctuation.
    company = company.rstrip(" ,;:|-.")

    return company or None


def _compare_party(a, b) -> str:
    a_norm = _normalize_party(a)
    b_norm = _normalize_party(b)

    if a_norm is None or b_norm is None:
        return "UNKNOWN"

    if a_norm == b_norm:
        return "MATCH"

    return "MISMATCH"


def _normalize_text(value):
    if _is_missing(value):
        return None

    text = str(value).upper().strip()
    text = re.sub(r"\s+", " ", text)

    return text


def _compare_text(a, b) -> str:
    a_norm = _normalize_text(a)
    b_norm = _normalize_text(b)

    if a_norm is None or b_norm is None:
        return "UNKNOWN"

    return (
        "MATCH"
        if a_norm == b_norm
        else "MISMATCH"
    )


def _parse_port(value):
    """
    Parse a port into:

        name
        country
        code

    Examples:

        VALPARAISO, CHILE (CLVAP)

        HOUSTON, US (USHOU)

        NANTONG, CHINA (CNNTG)
    """

    if _is_missing(value):
        return {
            "name": None,
            "country": None,
            "code": None,
        }

    text = str(value).upper().strip()

    # Extract final five-letter UN/LOCODE.
    code_match = re.search(
        r"\(([A-Z]{5})\)\s*$",
        text,
    )

    code = (
        code_match.group(1)
        if code_match
        else None
    )

    if code_match:
        text = text[:code_match.start()].strip()

    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,;")

    name = text
    country = None

    # Most documents use:
    #
    # CITY, COUNTRY
    #
    if "," in text:
        parts = [
            part.strip()
            for part in text.split(",")
            if part.strip()
        ]

        if len(parts) >= 2:
            country = parts[-1]
            name = ", ".join(parts[:-1])

    return {
        "name": name or None,
        "country": country or None,
        "code": code,
    }


def _normalize_port_name(value):
    if value is None:
        return None

    text = str(value).upper().strip()

    text = re.sub(
        r"/+",
        "/",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip(" ,;")


def _port_names_compatible(a, b) -> bool:
    """
    Compare visible port names/countries.

    A matching LOCODE alone must NOT override a conflicting
    visible port name or country.
    """

    a_name = _normalize_port_name(
        a.get("name")
    )

    b_name = _normalize_port_name(
        b.get("name")
    )

    a_country = _normalize_port_name(
        a.get("country")
    )

    b_country = _normalize_port_name(
        b.get("country")
    )

    # Both have visible port names.
    if a_name and b_name:

        if a_name == b_name:

            if a_country and b_country:
                return a_country == b_country

            return True

        # Some documents contain:
        #
        # RUGAO/NANTONG/SHANGHAI
        #
        # while another may contain one or more of those names.
        a_parts = {
            part.strip()
            for part in a_name.split("/")
            if part.strip()
        }

        b_parts = {
            part.strip()
            for part in b_name.split("/")
            if part.strip()
        }

        if (
            a_parts
            and b_parts
            and (
                a_parts.issubset(b_parts)
                or b_parts.issubset(a_parts)
            )
        ):
            if a_country and b_country:
                return a_country == b_country

            return True

        return False

    # Neither has a visible name.
    if not a_name and not b_name:
        if (
            a.get("code")
            and b.get("code")
            and a["code"] == b["code"]
        ):
            return True

    return False


def _compare_port(a, b) -> str:
    a_port = _parse_port(a)
    b_port = _parse_port(b)

    a_empty = (
        a_port["name"] is None
        and a_port["country"] is None
        and a_port["code"] is None
    )

    b_empty = (
        b_port["name"] is None
        and b_port["country"] is None
        and b_port["code"] is None
    )

    if a_empty or b_empty:
        return "UNKNOWN"

    # If both explicitly provide LOCODEs and they differ,
    # treat that as a mismatch.
    #
    # This is checked before name compatibility.
    if (
        a_port["code"]
        and b_port["code"]
        and a_port["code"] != b_port["code"]
    ):
        return "MISMATCH"

    # Visible name/country remains authoritative.
    if _port_names_compatible(a_port, b_port):
        return "MATCH"

    return "MISMATCH"