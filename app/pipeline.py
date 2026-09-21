import json
import os
from loader import Inbox
from classifier import classify
from extractor import extract_fields
from comparator import compare
from escalation import check_review

def read_attachment_text(inbox: Inbox, path: str) -> str | None:
    """Return plain text for an attachment, or None if unreadable/empty."""
    try:
        raw = inbox.read_bytes(path)
    except Exception:
        return None
    if not raw:
        return None
    if path.endswith(".txt"):
        return raw.decode("utf-8", errors="replace")
    if path.endswith(".pdf"):
        return _pdf_text(raw)
    if path.endswith(".docx"):
        return _docx_text(raw)
    if path.endswith(".xlsx"):
        return _xlsx_text(raw)
    return None

def _pdf_text(raw: bytes) -> str | None:
    import io
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        return text if len(text.strip()) > 10 else None  # image-only -> None
    except Exception:
        return None

def _docx_text(raw: bytes) -> str | None:
    import io
    from docx import Document
    try:
        d = Document(io.BytesIO(raw))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    except Exception:
        return None

def _xlsx_text(raw: bytes) -> str | None:
    import io
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
        ws = wb.active
        rows = ["\t".join(str(c) if c is not None else "" for c in row)
                for row in ws.iter_rows(values_only=True)]
        return "\n".join(rows)
    except Exception:
        return None

def process_email(inbox: Inbox, email: dict) -> dict:
    eid = email["email_id"]
    result = {"category": "GENERAL", "status": "OK", "review_reason": None,
               "defect_fields": [], "has_defect": False}

    cls = classify(email)
    result["category"] = cls["category"]

    if result["category"] != "BL_COMPARISON":
        return result

    atts = email.get("attachments", [])
    si_path = next((a for a in atts if "_SI" in a), None)
    bl_path = next((a for a in atts if "_BL" in a), None)

    si_text = read_attachment_text(inbox, si_path) if si_path else None
    bl_text = read_attachment_text(inbox, bl_path) if bl_path else None

    si_fields = extract_fields(si_text) if si_text else None
    bl_fields = extract_fields(bl_text) if bl_text else None

    reason = check_review(email, si_text, bl_text, si_fields, bl_fields)
    if reason:
        result["status"] = "NEEDS_REVIEW"
        result["review_reason"] = reason
        return result

    # Safety check: never send failed extraction results to comparator
    if si_fields is None or bl_fields is None:
        result["status"] = "NEEDS_REVIEW"
        result["review_reason"] = "extraction_failed"
        return result

    has_defect, defects = compare(si_fields, bl_fields)
    result["status"] = "MISMATCH" if has_defect else "OK"
    result["has_defect"] = has_defect
    result["defect_fields"] = defects
    return result

def process_one(source: str, email_id: str):
    """Test a single email and print the result — no file writes."""
    inbox = Inbox(source)
    email = inbox.get(email_id)
    result = process_email(inbox, email)
    print(json.dumps({email_id: result}, indent=2))
    return result


def run(source: str, out_path: str = "submission.json"):
    inbox = Inbox(source)
    emails = list(inbox)

    # resume: load whatever's already been written, skip those email_ids
    submission = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            submission = json.load(f)
        print(f"resuming: {len(submission)} already done, skipping those")

    remaining = [e for e in emails if e["email_id"] not in submission]
    print(f"{len(remaining)}/{len(emails)} left to process")

    for i, email in enumerate(remaining, 1):
        eid = email["email_id"]
        try:
            submission[eid] = process_email(inbox, email)
        except Exception as e:
            # STOP on failure instead of silently writing a GENERAL/OK stub,
            # so you can inspect and restart from exactly this email
            print(f"[FAILED] {eid}: {e}")
            with open(out_path, "w") as f:
                json.dump(submission, f, indent=2)
            print(f"progress saved to {out_path} ({len(submission)} done). "
                  f"Fix the issue and re-run — it will resume from {eid}.")
            raise

        if i % 10 == 0:
            with open(out_path, "w") as f:
                json.dump(submission, f, indent=2)
            print(f"{len(submission)}/{len(emails)} done (checkpoint saved)")

    with open(out_path, "w") as f:
        json.dump(submission, f, indent=2)
    print(f"done: wrote {out_path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "test":
        src = sys.argv[3] if len(sys.argv) > 3 else "."
        process_one(src, sys.argv[2])
    else:
        src = sys.argv[1] if len(sys.argv) > 1 else "."
        run(src)