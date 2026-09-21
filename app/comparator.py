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
        if field in (
            "container_count",
            "gross_weight_kg",
        ):
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

    # ---------------------------------------------------------
    # Remove common field labels
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Keep the main company identity.
    #
    # Example:
    #
    # APRIL FINE PAPER TRADING
    # ON BEHALF OF VITAL SOLUTIONS PTE LTD
    #
    # becomes:
    #
    # APRIL FINE PAPER TRADING
    # ---------------------------------------------------------

    text = re.sub(
        r"\bON\s+BEHALF\s+OF\b.*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # ---------------------------------------------------------
    # Normalize separators
    # ---------------------------------------------------------

    text = re.sub(
        r"[|;]+",
        "\n",
        text,
    )

    text = re.sub(
        r"\r\n?",
        "\n",
        text,
    )

    # ---------------------------------------------------------
    # Remove address/details after the company name.
    #
    # Shipping documents commonly put the company name first,
    # followed by:
    #
    # - P.O. BOX
    # - street address
    # - postal code
    # - GST number
    # ---------------------------------------------------------

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
    ]

    # Ignore descriptor-only lines such as "(Non-Negotiable)"
    while lines and re.fullmatch(r"\([^)]*\)", lines[0]):
        lines.pop(0)

    if lines:
        text = lines[0]

    # ---------------------------------------------------------
    # Remove remaining common punctuation / whitespace.
    # ---------------------------------------------------------

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    # Company identity comparison should not depend on spaces.
    text = re.sub(
        r"\s+",
        "",
        text,
    )

    return text or None

def _normalize_port(value):
    """
    Normalize formatting differences in port names.
    """

    if value is None:
        return None

    text = str(value).upper()

    text = re.sub(r"[|;]+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()