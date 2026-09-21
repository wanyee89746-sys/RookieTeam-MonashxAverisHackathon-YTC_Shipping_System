import re

from extractor import FIELDS


def compare(
    si: dict,
    bl: dict
) -> tuple[bool, list[str]]:

    mismatches = []

    for field in FIELDS:

        a = si.get(field)
        b = bl.get(field)

        # Numeric fields
        if field in ("container_count", "gross_weight_kg"):
            # Missing gross weight is not treated as a BL defect.
            if field == "gross_weight_kg":
                if a is None or b is None:
                    continue

            # Container count must exist on both sides.
            if a is None or b is None:
                mismatches.append(field)
                continue

            try:
                if int(a) != int(b):
                    mismatches.append(field)
            except (ValueError, TypeError):
                mismatches.append(field)

            continue

        # Port fields
        if field in (
            "port_of_loading",
            "port_of_discharge",
        ):
            if _normalize_port(a) != _normalize_port(b):
                mismatches.append(field)

            continue

        # Party fields
        if _normalize_party(a) != _normalize_party(b):
            mismatches.append(field)

    return (
        len(mismatches) > 0,
        sorted(mismatches)
    )


def _normalize_party(value):
    if value is None:
        return None

    text = str(value).upper()

    # Remove common field labels
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

    # Remove descriptors such as:
    # (Non-Negotiable):
    # (Principal or Seller):
    text = re.sub(
        r"^\s*\([^)]*\)\s*[:：-]?\s*",
        "",
        text,
    )

    # Keep the actual company identity.
    # Example:
    # APRIL FINE PAPER TRADING
    # ON BEHALF OF VITAL SOLUTIONS PTE LTD
    # ...
    # -> APRIL FINE PAPER TRADING
    text = re.sub(
        r"\bON\s+BEHALF\s+OF\b.*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Normalize separators
    text = re.sub(r"[|;]+", "\n", text)
    text = re.sub(r"\r\n?", "\n", text)

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
    ]

    # Ignore descriptor-only lines
    while lines and re.fullmatch(r"\([^)]*\)", lines[0]):
        lines.pop(0)

    if lines:
        text = lines[0]

    text = re.sub(r"\s+", " ", text).strip()

    # Ignore whitespace when comparing company names
    text = re.sub(r"\s+", "", text)

    return text or None

def _normalize_port(value):
    if value is None:
        return None

    text = str(value).upper()

    text = re.sub(r"[|;]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Remove trailing UN/LOCODE such as:
    # (SGSIN)
    # (KRPTK)
    # (AUBNE)
    # (TRMER)
    text = re.sub(
        r"\s*\([A-Z]{5}\)\s*$",
        "",
        text,
    )

    return text.strip()