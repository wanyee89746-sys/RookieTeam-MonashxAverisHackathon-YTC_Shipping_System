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
    # ---------------------------------------------------------
    for label, text in [("SI", si_text), ("BL", bl_text)]:
        upper = text.upper()

        if any(
            marker in upper
            for marker in [
                "COMMERCIAL INVOICE",
                "PACKING LIST",
                "CERTIFICATE OF ORIGIN",
            ]
        ):
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