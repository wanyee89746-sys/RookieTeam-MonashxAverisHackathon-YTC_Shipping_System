from extractor import FIELDS


BLANK_TOKENS = {
    "???",
    "___",
    "_______",
    "TBA",
    "TBC",
    "N/A",
    "NA",
    "NULL",
    "NONE",
    "",
    "____MT",
}


WRONG_DOC_MARKERS = [
    "COMMERCIAL INVOICE",
    "PACKING LIST",
    "CERTIFICATE OF ORIGIN",
]


def check_review(
    email: dict,
    si_text: str | None,
    bl_text: str | None,
    si_fields: dict | None,
    bl_fields: dict | None,
) -> str | None:
    """Return a review reason, or None if the case can proceed."""

    attachments = email.get("attachments", [])

    si_path = next(
        (a for a in attachments if "_SI" in a),
        None,
    )

    bl_path = next(
        (a for a in attachments if "_BL" in a),
        None,
    )

    # ---------------------------------------------------------
    # 1. Missing attachment
    # ---------------------------------------------------------

    if si_path is None or bl_path is None:

        body = (
            email.get("body") or ""
        ).upper()

        missing_attachment_phrases = [
            "ATTACHMENTS APPEAR TO HAVE BEEN DROPPED",
            "ATTACHMENT APPEARS TO HAVE BEEN DROPPED",
            "DRAFT BL IS STILL MISSING",
            "DRAFT BL IS MISSING",
            "BL IS STILL MISSING",
            "BL IS MISSING",
            "ATTACHMENT IS MISSING",
            "ATTACHMENTS ARE MISSING",
        ]

        if any(
            phrase in body
            for phrase in missing_attachment_phrases
        ):
            return "missing_attachment"

        # No explicit statement that the attachment is missing.
        # Keep the original behaviour for these cases.
        return None

    # ---------------------------------------------------------
    # 2. Readability
    # ---------------------------------------------------------

    if si_text is None or not si_text.strip():
        return "unreadable"

    if bl_text is None or not bl_text.strip():
        return "unreadable"

    if len(si_text.strip()) < 20:
        return "unreadable"

    if len(bl_text.strip()) < 20:
        return "unreadable"

    # ---------------------------------------------------------
    # 3. Wrong document type
    # ---------------------------------------------------------

    for label, text in [
        ("SI", si_text),
        ("BL", bl_text),
    ]:

        upper = text.upper()

        if any(
            marker in upper
            for marker in WRONG_DOC_MARKERS
        ):
            return "wrong_doc_type"

    # ---------------------------------------------------------
    # 4. Extraction completely failed
    # ---------------------------------------------------------

    if si_fields is None or bl_fields is None:
        return "extraction_failed"

    # ---------------------------------------------------------
    # 5. Check whether the extraction is almost completely empty.
    #
    # We only use this as a wrong-document signal when BOTH sides
    # have almost no recognized fields.
    #
    # We do NOT escalate because one or two fields are missing.
    # Missing fields are handled as UNKNOWN by comparator.py.
    # ---------------------------------------------------------

    si_hits = sum(
        1
        for f in FIELDS
        if not _is_blank(si_fields.get(f))
    )

    bl_hits = sum(
        1
        for f in FIELDS
        if not _is_blank(bl_fields.get(f))
    )

    if si_hits <= 1 and bl_hits <= 1:
        return "wrong_doc_type"

    # ---------------------------------------------------------
    # 6. Missing individual fields
    #
    # IMPORTANT:
    #
    # Do NOT return "missing_value" here.
    #
    # Examples:
    #
    # SI weight = 214270
    # BL weight = None
    #
    # This is not automatically a mismatch.
    #
    # Comparator will represent it as:
    #
    # gross_weight_kg -> UNKNOWN
    #
    # This prevents extraction/document incompleteness from being
    # confused with an actual SI/BL value disagreement.
    # ---------------------------------------------------------

    return None


def _is_blank(value) -> bool:

    if value is None:
        return True

    text = str(value).strip().upper()

    return text in BLANK_TOKENS