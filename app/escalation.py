from extractor import FIELDS

BLANK_TOKENS = {"???", "___", "_______", "TBA", "TBC", "N/A", "", "____MT"}

def check_review(email: dict, si_text: str | None, bl_text: str | None,
                  si_fields: dict | None, bl_fields: dict | None) -> str | None:
    """Returns a review_reason string, or None if the case can proceed to compare()."""
    attachments = email.get("attachments", [])

    if len(attachments) < 2:
        return "missing_attachment"

    if si_text is not None and len(si_text.strip()) < 20:
        return "unreadable"
    if bl_text is not None and len(bl_text.strip()) < 20:
        return "unreadable"
    if si_text is None or bl_text is None:
        return "unreadable"

    # wrong_doc_type: a doc that doesn't look like an SI/BL at all
    for label, text in [("SI", si_text), ("BL", bl_text)]:
        upper = text.upper()
        if any(marker in upper for marker in
               ["COMMERCIAL INVOICE", "PACKING LIST", "CERTIFICATE OF ORIGIN"]):
            return "wrong_doc_type"

    # missing_value: a required field came back blank/placeholder
    for f in FIELDS:
        if si_fields and (si_fields.get(f) is None or str(si_fields.get(f)) in BLANK_TOKENS):
            return "missing_value"
        if bl_fields and (bl_fields.get(f) is None or str(bl_fields.get(f)) in BLANK_TOKENS):
            return "missing_value"

    return None