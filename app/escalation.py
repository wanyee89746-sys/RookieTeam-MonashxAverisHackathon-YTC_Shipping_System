from extractor import FIELDS

BLANK_TOKENS = {
    "???",
    "___",
    "_______",
    "TBA",
    "TBC",
    "N/A",
    "",
    "____MT",
}

# Literal markers this dataset's generator prints for "wrong" documents.
# Kept as a fast, exact fast-path — but NOT the only signal (see the
# structural fallback in step 3 below), so a real inbox's differently
# worded invoices/packing lists still get caught.
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

    si_path = next((a for a in attachments if "_SI" in a), None)
    bl_path = next((a for a in attachments if "_BL" in a), None)

    # ---------------------------------------------------------
    # 1. Missing attachment
    # ---------------------------------------------------------
    if si_path is None or bl_path is None:
        body = (email.get("body") or "").upper()

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

        if any(phrase in body for phrase in missing_attachment_phrases):
            return "missing_attachment"

        # Some emails are valid BL comparison requests even though
        # the attachments are not actually present in the dataset.
        # Do not automatically escalate unless the email explicitly
        # indicates that an attachment is missing.
        return None

    # ---------------------------------------------------------
    # 2. Both attachments exist → check readability
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
    # 3. Check whether attachments are obviously wrong documents
    #
    #    a) Literal markers first — exact, cheap, catches this
    #       dataset's generated wrong-doc text immediately.
    #    b) Structural fallback — if extraction already ran and
    #       came back with almost nothing usable despite the
    #       document being readable and non-empty, it's more
    #       likely the wrong document type than a parsing bug.
    #       This generalizes beyond the exact strings above, so
    #       the check doesn't only work on this generator's output.
    # ---------------------------------------------------------
    for label, text in [("SI", si_text), ("BL", bl_text)]:
        upper = text.upper()

        if any(marker in upper for marker in WRONG_DOC_MARKERS):
            return "wrong_doc_type"

    if si_fields is not None and bl_fields is not None:
        si_hits = sum(
            1 for f in FIELDS
            if si_fields.get(f) not in (None, "")
        )
        bl_hits = sum(
            1 for f in FIELDS
            if bl_fields.get(f) not in (None, "")
        )

        # A genuine SI/BL should yield multiple recognizable fields.
        # Almost nothing extracted from a readable, non-empty
        # document suggests it isn't an SI/BL at all.
        if si_hits <= 1 or bl_hits <= 1:
            return "wrong_doc_type"

    # ---------------------------------------------------------
    # 4. Extraction completely failed
    # ---------------------------------------------------------
    if si_fields is None or bl_fields is None:
        return "extraction_failed"

    # ---------------------------------------------------------
    # 5. Missing required values
    #
    # Only escalate when a field is missing on ONE side but
    # present on the other side.
    #
    # If both SI and BL are missing the same field, there is
    # no discrepancy to report, so comparison can continue.
    # ---------------------------------------------------------
    for f in FIELDS:

        si_missing = (
            si_fields.get(f) is None
            or str(si_fields.get(f)).strip().upper() in BLANK_TOKENS
        )

        bl_missing = (
            bl_fields.get(f) is None
            or str(bl_fields.get(f)).strip().upper() in BLANK_TOKENS
        )

        if si_missing != bl_missing:
            return "missing_value"

    # ---------------------------------------------------------
    # 6. Everything is usable → continue to comparison
    # ---------------------------------------------------------
    return None