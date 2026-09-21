from extractor import FIELDS, is_missing_value


BLANK_TOKENS = {
    "???",
    "___",
    "_______",
    "TBA",
    "TBC",
    "N/A",
    "NA",
    "NIL",
    "NONE",
    "NULL",
    "",
    "____MT",
}


WRONG_DOC_MARKERS = [
    "COMMERCIAL INVOICE",
    "PACKING LIST",
    "CERTIFICATE OF ORIGIN",
]


def _is_missing(value) -> bool:
    """
    Detect an explicitly missing/placeholder field value.
    """
    if is_missing_value(value):
        return True

    if value is None:
        return True

    text = str(value).strip().upper()

    if text in BLANK_TOKENS:
        return True

    return False


def _get_explicit_missing(fields: dict | None, field: str) -> bool:
    """
    The extractor stores information about fields that were explicitly
    present but blank, e.g.:

        CONSIGNEE:
        GROSS WEIGHT: N/A
        POD: TBA
    """
    if not fields:
        return False

    metadata = fields.get("_explicit_missing")

    if not isinstance(metadata, dict):
        return False

    return bool(metadata.get(field, False))


def _has_explicit_missing_field(
    fields: dict | None,
) -> bool:
    if not fields:
        return False

    for field in FIELDS:
        if not _get_explicit_missing(fields, field):
            continue

        # If extraction successfully produced a real value,
        # the field is NOT actually missing.
        value = fields.get(field)

        if not _is_missing(value):
            continue

        return True

    return False


def check_review(
    email: dict,
    si_text: str | None,
    bl_text: str | None,
    si_fields: dict | None,
    bl_fields: dict | None,
) -> str | None:
    """
    Determine whether the comparison should be escalated for review.

    Review reasons:
        missing_attachment
        unreadable
        wrong_doc_type
        extraction_failed
        missing_value
    """

    attachments = email.get("attachments", [])

    si_path = next(
        (a for a in attachments if "_SI" in a),
        None,
    )

    bl_path = next(
        (a for a in attachments if "_BL" in a),
        None,
    )

    # ------------------------------------------------------------
    # 1. Missing attachment
    # ------------------------------------------------------------
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

        if any(
            phrase in body
            for phrase in missing_attachment_phrases
        ):
            return "missing_attachment"

        return None

    # ------------------------------------------------------------
    # 2. Unreadable documents
    # ------------------------------------------------------------
    if si_text is None or not si_text.strip():
        return "unreadable"

    if bl_text is None or not bl_text.strip():
        return "unreadable"

    if len(si_text.strip()) < 20:
        return "unreadable"

    if len(bl_text.strip()) < 20:
        return "unreadable"

    # ------------------------------------------------------------
    # 3. Wrong document type
    # ------------------------------------------------------------
    for text in (si_text, bl_text):
        upper = text.upper()

        if any(
            marker in upper
            for marker in WRONG_DOC_MARKERS
        ):
            return "wrong_doc_type"

    # ------------------------------------------------------------
    # 4. Extraction failure / obviously wrong documents
    # ------------------------------------------------------------
    if si_fields is not None and bl_fields is not None:
        si_hits = sum(
            1
            for field in FIELDS
            if si_fields.get(field) not in (None, "")
        )

        bl_hits = sum(
            1
            for field in FIELDS
            if bl_fields.get(field) not in (None, "")
        )

        # If BOTH documents contain almost no recognizable shipping
        # fields, this is more consistent with a wrong/unusable
        # document than an ordinary comparison.
        if si_hits <= 1 and bl_hits <= 1:
            return "wrong_doc_type"

    if si_fields is None or bl_fields is None:
        return "extraction_failed"

    # ------------------------------------------------------------
    # 5. Explicit missing values
    # ------------------------------------------------------------
    #
    # Important:
    #
    #   CONSIGNEE:
    #   SHIPPER:
    #   POD: N/A
    #   Gross Weight: ____MT
    #
    # must be recognized BEFORE comparison.
    #
    # This prevents the comparator from treating the next field's
    # value as the current field's value.
    #
    # We specifically prioritize explicit SI blanks because the
    # dataset's review rule is about customer-provided SI fields
    # being left blank.
    #
    if _has_explicit_missing_field(si_fields):
        return "missing_value"

    # Also handle a field that is genuinely represented as a missing
    # value in SI while the BL contains a value.
    for field in FIELDS:
        si_missing = _is_missing(si_fields.get(field))
        bl_missing = _is_missing(bl_fields.get(field))

        if si_missing and not bl_missing:
            return "missing_value"

    return None