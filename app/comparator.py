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
    """
    Normalize formatting differences in shipper,
    consignee and notify-party values.
    """

    if value is None:
        return None

    text = str(value).upper()

    # Remove document/table separators.
    text = re.sub(r"[|;]+", " ", text)

    # Remove common Chinese field descriptions
    # that sometimes leak into extracted values.
    text = re.sub(
        r"\(\s*(?:发货人|收货人|通知人)\s*\)",
        " ",
        text,
    )

    # Remove common English field labels if they
    # accidentally appear inside the extracted value.
    text = re.sub(
        r"\b(?:SHIPPER|EXPORTER)\s*[:：-]?\s*",
        " ",
        text,
    )

    text = re.sub(
        r"\b(?:CONSIGNEE)\s*[:：-]?\s*",
        " ",
        text,
    )

    text = re.sub(
        r"\b(?:NOTIFY PARTY|NOTIFY)\s*[:：-]?\s*",
        " ",
        text,
    )

    # Normalize whitespace.
    text = re.sub(r"\s+", " ", text).strip()

    # Formatting-only difference:
    # VITAL SOLUTIONS
    # VITALSOLUTIONS
    #
    # UNITED ARAB
    # UNITEDARAB
    text = re.sub(r"\s+", "", text)

    return text


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