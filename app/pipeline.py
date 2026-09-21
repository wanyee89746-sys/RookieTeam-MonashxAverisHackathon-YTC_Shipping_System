import json
import os
import random

from loader import Inbox
from classifier import classify_batch
from extractor import extract_fields
from comparator import compare, compare_detailed
from escalation import check_review


def read_attachment_text(
    inbox: Inbox,
    path: str,
    return_metadata: bool = False,
):
    """
    Return attachment text.

    Standard extraction is attempted first.

    If a PDF contains no usable text, Gemini Vision is used
    as a fallback.

    When return_metadata=True, also return information about
    which extraction method was used.

    Extraction metadata does not affect verification status.
    """

    metadata = {
        "extraction_method": "standard",
        "vision_used": False,
        "vision_success": False,
    }

    try:
        raw = inbox.read_bytes(path)

    except Exception:
        if return_metadata:
            return None, metadata

        return None

    if not raw:
        if return_metadata:
            return None, metadata

        return None

    # ---------------------------------------------------------
    # TXT
    # ---------------------------------------------------------

    if path.endswith(".txt"):

        text = raw.decode(
            "utf-8",
            errors="replace",
        )

        if return_metadata:
            return text, metadata

        return text

    # ---------------------------------------------------------
    # PDF
    # ---------------------------------------------------------

    if path.endswith(".pdf"):

        text = _pdf_text(raw)

        # Standard extraction worked
        if text:

            if return_metadata:
                return text, metadata

            return text

        # -----------------------------------------------------
        # Standard extraction failed.
        # Use Vision LLM.
        # -----------------------------------------------------

        print(
            f"[VISION] No readable PDF text: {path}"
        )

        metadata["vision_used"] = True
        metadata["extraction_method"] = "vision_llm"

        vision_text = _pdf_vision_text(
            raw,
            path,
        )

        if vision_text:
            metadata["vision_success"] = True

        if return_metadata:
            return vision_text, metadata

        return vision_text

    # ---------------------------------------------------------
    # DOCX
    # ---------------------------------------------------------

    if path.endswith(".docx"):

        text = _docx_text(raw)

        if return_metadata:
            return text, metadata

        return text

    # ---------------------------------------------------------
    # XLSX
    # ---------------------------------------------------------

    if path.endswith(".xlsx"):

        text = _xlsx_text(raw)

        if return_metadata:
            return text, metadata

        return text

    # ---------------------------------------------------------
    # Unsupported file
    # ---------------------------------------------------------

    if return_metadata:
        return None, metadata

    return None


def _pdf_text(raw: bytes) -> str | None:

    import io

    from pypdf import PdfReader

    try:

        reader = PdfReader(
            io.BytesIO(raw)
        )

        text = "\n".join(
            (p.extract_text() or "")
            for p in reader.pages
        )

        return (
            text
            if len(text.strip()) > 10
            else None
        )

    except Exception:
        return None


def _pdf_vision_text(
    raw: bytes,
    path: str,
) -> str | None:
    """
    Render PDF pages as images and ask Gemini Vision
    to extract the seven shipping fields.

    Returns ordinary labelled text so the existing
    extract_fields() function can process it.

    No temporary image files are created.
    """

    import io

    from dotenv import load_dotenv
    from PIL import Image
    import pymupdf
    from google import genai

    try:

        # -----------------------------------------------------
        # Load API key
        # -----------------------------------------------------

        load_dotenv("app/.env")

        api_key = os.getenv(
            "GEMINI_API_KEY"
        )

        if not api_key:

            print(
                "[VISION] GEMINI_API_KEY not found"
            )

            return None

        # -----------------------------------------------------
        # Open PDF directly from memory
        # -----------------------------------------------------

        doc = pymupdf.open(
            stream=raw,
            filetype="pdf",
        )

        if len(doc) == 0:

            print(
                f"[VISION] PDF has no pages: {path}"
            )

            return None

        # -----------------------------------------------------
        # Render up to first 5 pages
        # -----------------------------------------------------

        images = []

        for page_number, page in enumerate(doc):

            if page_number >= 5:
                break

            pix = page.get_pixmap(
                matrix=pymupdf.Matrix(2, 2),
                alpha=False,
            )

            image = Image.open(
                io.BytesIO(
                    pix.tobytes("png")
                )
            )

            images.append(image)

        if not images:
            return None

        # -----------------------------------------------------
        # Gemini Vision
        # -----------------------------------------------------

        client = genai.Client(
            api_key=api_key
        )

        prompt = """
You are extracting data from a shipping document.

Read the document image carefully, including tables,
headers, labels, and values.

Extract ONLY these seven fields:

shipper
consignee
notify_party
port_of_loading
port_of_discharge
container_count
gross_weight_kg

Return exactly this format:

SHIPPER: value
CONSIGNEE: value
NOTIFY PARTY: value
PORT OF LOADING: value
PORT OF DISCHARGE: value
CONTAINER COUNT: value
GROSS WEIGHT: value

Rules:
- Preserve company names accurately.
- Preserve port names accurately.
- For container count, return only the number when clearly shown.
- For gross weight, return the numeric weight in kg when clearly shown.
- If a field is not visible or cannot be determined, write:
  NOT FOUND
- Do not guess.
- Do not add explanations.
"""

        contents = [prompt]
        contents.extend(images)

        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=contents,
        )

        text = getattr(
            response,
            "text",
            None,
        )

        if not text:

            print(
                f"[VISION] Gemini returned no text: {path}"
            )

            return None

        print(
            f"[VISION] Successfully extracted: {path}"
        )

        return text

    except Exception as e:

        print(
            f"[VISION] Failed for {path}: {e}"
        )

        return None


def _docx_text(raw: bytes) -> str | None:

    import io

    from docx import Document

    try:

        d = Document(
            io.BytesIO(raw)
        )

        parts = [
            p.text
            for p in d.paragraphs
        ]

        for t in d.tables:

            for row in t.rows:

                parts.append(
                    " | ".join(
                        c.text
                        for c in row.cells
                    )
                )

        return "\n".join(parts)

    except Exception:
        return None


def _xlsx_text(raw: bytes) -> str | None:

    import io
    import openpyxl

    try:

        wb = openpyxl.load_workbook(
            io.BytesIO(raw),
            data_only=True,
        )

        ws = wb.active

        rows = [
            "\t".join(
                str(c)
                if c is not None
                else ""
                for c in row
            )
            for row in ws.iter_rows(
                values_only=True
            )
        ]

        return "\n".join(rows)

    except Exception:
        return None


def process_comparison(
    inbox: Inbox,
    email: dict,
) -> dict:
    """
    Runs extraction, comparison, and escalation for an email
    that has already been classified as BL_COMPARISON.

    Gemini Vision may be used when standard PDF extraction
    cannot read the document.

    IMPORTANT:
    If standard extraction fails and Vision successfully
    recovers the document, the recovered text may still be
    used for extraction.

    However, the official verification result remains
    NEEDS_REVIEW with reason "unreadable" because the
    original document was unreadable to the standard
    extraction process.

    Vision recovery is stored separately as metadata so the
    frontend can demonstrate the AI capability without
    changing the official evaluation result.
    """

    result = {
        # -----------------------------------------------------
        # Evaluation fields
        # -----------------------------------------------------

        "category": "BL_COMPARISON",
        "status": "OK",
        "review_reason": None,
        "defect_fields": [],
        "has_defect": False,

        # -----------------------------------------------------
        # Extraction metadata
        # -----------------------------------------------------

        "si_extraction_method": "standard",
        "si_vision_used": False,
        "si_vision_success": False,

        "bl_extraction_method": "standard",
        "bl_vision_used": False,
        "bl_vision_success": False,
    }

    atts = email.get(
        "attachments",
        [],
    )

    # ---------------------------------------------------------
    # Find SI and BL
    # ---------------------------------------------------------

    si_path = next(
        (
            a
            for a in atts
            if "_SI" in a
        ),
        None,
    )

    bl_path = next(
        (
            a
            for a in atts
            if "_BL" in a
        ),
        None,
    )

    si_text = None
    bl_text = None

    # ---------------------------------------------------------
    # SI extraction
    # ---------------------------------------------------------

    if si_path:

        si_text, si_meta = read_attachment_text(
            inbox,
            si_path,
            return_metadata=True,
        )

        result["si_extraction_method"] = (
            si_meta.get(
                "extraction_method",
                "standard",
            )
        )

        result["si_vision_used"] = (
            si_meta.get(
                "vision_used",
                False,
            )
        )

        result["si_vision_success"] = (
            si_meta.get(
                "vision_success",
                False,
            )
        )

    # ---------------------------------------------------------
    # BL extraction
    # ---------------------------------------------------------

    if bl_path:

        bl_text, bl_meta = read_attachment_text(
            inbox,
            bl_path,
            return_metadata=True,
        )

        result["bl_extraction_method"] = (
            bl_meta.get(
                "extraction_method",
                "standard",
            )
        )

        result["bl_vision_used"] = (
            bl_meta.get(
                "vision_used",
                False,
            )
        )

        result["bl_vision_success"] = (
            bl_meta.get(
                "vision_success",
                False,
            )
        )

    # ---------------------------------------------------------
    # Remember whether the ORIGINAL standard extraction
    # failed.
    #
    # This is important because Vision may successfully
    # recover text afterwards.
    # ---------------------------------------------------------

    original_unreadable = (
        result["si_vision_used"]
        or result["bl_vision_used"]
    )

    # ---------------------------------------------------------
    # Extract fields
    #
    # If Vision succeeded, extract_fields() can still process
    # the recovered text.
    # ---------------------------------------------------------

    si_fields = (
        extract_fields(si_text)
        if si_text
        else None
    )

    bl_fields = (
        extract_fields(bl_text)
        if bl_text
        else None
    )

    # ---------------------------------------------------------
    # Escalation checks
    # ---------------------------------------------------------

    reason = check_review(
        email,
        si_text,
        bl_text,
        si_fields,
        bl_fields,
    )

    # ---------------------------------------------------------
    # OPTION A:
    #
    # If standard extraction originally failed, preserve
    # the official unreadable-document review result even
    # when Vision successfully recovered the text.
    #
    # Vision metadata remains available to the frontend.
    # ---------------------------------------------------------

    if original_unreadable:

        result["status"] = "NEEDS_REVIEW"
        result["review_reason"] = "unreadable"

        return result

    # ---------------------------------------------------------
    # Other escalation reasons
    # ---------------------------------------------------------

    if reason:

        result["status"] = "NEEDS_REVIEW"
        result["review_reason"] = reason

        return result

    # ---------------------------------------------------------
    # No attachments
    # ---------------------------------------------------------

    if (
        si_path is None
        and bl_path is None
    ):

        return result

    # ---------------------------------------------------------
    # Extraction safety check
    # ---------------------------------------------------------

    if (
        si_fields is None
        or bl_fields is None
    ):

        result["status"] = "NEEDS_REVIEW"
        result["review_reason"] = "extraction_failed"

        return result

    # ---------------------------------------------------------
    # Detailed comparison
    # ---------------------------------------------------------

    detailed = compare_detailed(
        si_fields,
        bl_fields,
    )

    has_defect = detailed["has_defect"]
    defects = detailed["defect_fields"]

    result["status"] = (
        "MISMATCH"
        if has_defect
        else "OK"
    )

    result["has_defect"] = has_defect
    result["defect_fields"] = defects

    # ---------------------------------------------------------
    # Detailed field-level information
    # ---------------------------------------------------------

    result["field_results"] = (
        detailed["field_results"]
    )

    result["field_values"] = (
        detailed["field_values"]
    )

    return result


def vision_test(
    source: str,
    attachment_path: str,
):
    """Test Gemini Vision directly on one PDF attachment."""

    inbox = Inbox(source)

    raw = inbox.read_bytes(
        attachment_path
    )

    result = _pdf_vision_text(
        raw,
        attachment_path,
    )

    print(
        "\n===== VISION TEST RESULT ====="
    )

    if result:
        print(result)
    else:
        print("Vision extraction failed.")

    return result


def process_one(
    source: str,
    email_id: str,
):
    """
    Test a single email end-to-end and print the result.

    No file writes.
    """

    inbox = Inbox(source)

    email = inbox.get(
        email_id
    )

    classified = classify_batch(
        [email]
    )

    cat = classified[
        email_id
    ]["category"]

    if cat != "BL_COMPARISON":

        result = {
            "category": cat,
            "status": "OK",
            "review_reason": None,
            "defect_fields": [],
            "has_defect": False,
        }

    else:

        result = process_comparison(
            inbox,
            email,
        )

    print(
        "\n" + "=" * 80
    )

    print(
        "SHIPPING DOCUMENT VERIFICATION"
    )

    print(
        "=" * 80
    )

    print(
        f"Email ID: {email_id}"
    )

    print(
        f"Category: {result['category']}"
    )

    print(
        f"Status:   {result['status']}"
    )

    # ---------------------------------------------------------
    # Vision information
    # ---------------------------------------------------------

    if result.get("bl_vision_used"):

        print(
            "\n[AI DOCUMENT RECOVERY]"
        )

        print(
            "BL standard extraction: FAILED"
        )

        if result.get("bl_vision_success"):

            print(
                "BL Vision LLM: SUCCESS"
            )

        else:

            print(
                "BL Vision LLM: FAILED"
            )

    if result.get("si_vision_used"):

        print(
            "\n[AI DOCUMENT RECOVERY]"
        )

        print(
            "SI standard extraction: FAILED"
        )

        if result.get("si_vision_success"):

            print(
                "SI Vision LLM: SUCCESS"
            )

        else:

            print(
                "SI Vision LLM: FAILED"
            )

    if result.get("review_reason"):

        print(
            f"Review reason: "
            f"{result['review_reason']}"
        )

    if result.get("field_values"):

        print(
            "\n" + "-" * 80
        )

        print(
            f"{'FIELD':<24}"
            f"{'SI VALUE':<26}"
            f"{'BL VALUE':<26}"
            f"RESULT"
        )

        print(
            "-" * 80
        )

        field_labels = {
            "shipper": "Shipper",
            "consignee": "Consignee",
            "notify_party": "Notify Party",
            "port_of_loading": "Port of Loading",
            "port_of_discharge": "Port of Discharge",
            "container_count": "Container Count",
            "gross_weight_kg": "Gross Weight (kg)",
        }

        for field, values in result[
            "field_values"
        ].items():

            si_value = str(
                values.get("si")
                if values.get("si") is not None
                else "NOT FOUND"
            )

            bl_value = str(
                values.get("bl")
                if values.get("bl") is not None
                else "NOT FOUND"
            )

            comparison = result[
                "field_results"
            ].get(
                field,
                "UNKNOWN",
            )

            print(
                f"{field_labels.get(field, field):<24}"
                f"{si_value[:25]:<26}"
                f"{bl_value[:25]:<26}"
                f"{comparison}"
            )

        print(
            "-" * 80
        )

    if result["status"] == "OK":

        print(
            "\nNo mismatch detected."
        )

    elif result["status"] == "MISMATCH":

        print(
            "\nMismatch detected in: "
            + ", ".join(
                result["defect_fields"]
            )
        )

    elif result["status"] == "NEEDS_REVIEW":

        print(
            "\nHuman review required."
        )


def _save(
    data: dict,
    path: str,
):
    """Write results to a JSON file."""

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def run(
    source: str,
    out_path: str = "submission.json",
    limit: int | None = None,
    resume: bool = False,
    only: list[str] | None = None,
):
    """
    Default: fresh run that overwrites out_path when it finishes.

    resume=True   continue an interrupted run
    only=[...]    re-process just those emails and merge into
                  existing results
    limit=N       process N emails, merged into existing results

    Progress is written to out_path + ".partial".
    """

    inbox = Inbox(source)

    emails = list(
        inbox
    )

    partial_path = (
        out_path + ".partial"
    )

    submission = {}

    keep_existing = (
        resume
        or only is not None
        or limit is not None
    )

    if keep_existing:

        candidates = (
            (partial_path, out_path)
            if resume
            else (out_path,)
        )

        for path in candidates:

            if os.path.exists(path):

                with open(
                    path,
                    encoding="utf-8",
                ) as f:

                    submission = json.load(f)

                print(
                    f"loaded {len(submission)} existing "
                    f"results from {path}"
                )

                break

    # ---------------------------------------------------------
    # Choose what to process
    # ---------------------------------------------------------

    if only is not None:

        wanted = set(
            only
        )

        remaining = [
            e
            for e in emails
            if e["email_id"] in wanted
        ]

        missing = (
            wanted
            - {
                e["email_id"]
                for e in remaining
            }
        )

        if missing:

            print(
                f"[WARN] unknown email IDs: "
                f"{sorted(missing)}"
            )

    else:

        remaining = [
            e
            for e in emails
            if e["email_id"]
            not in submission
        ]

    if limit is not None:

        remaining = remaining[:limit]

        print(
            f"[LIMIT] processing only "
            f"{len(remaining)} emails"
        )

    print(
        f"{len(remaining)}/{len(emails)} "
        f"to process"
    )

    if not remaining:

        print(
            f"nothing to do: "
            f"{out_path} already complete"
        )

        return

    # ---------------------------------------------------------
    # Stage 1: classification
    # ---------------------------------------------------------

    CLASSIFY_BATCH = 25

    classified = {}

    for i in range(
        0,
        len(remaining),
        CLASSIFY_BATCH,
    ):

        chunk = remaining[
            i:i + CLASSIFY_BATCH
        ]

        classified.update(
            classify_batch(chunk)
        )

        with open(
            "classification_debug.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                classified,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print(
            f"[CLASSIFY] "
            f"{min(i + CLASSIFY_BATCH, len(remaining))}"
            f"/{len(remaining)} classified"
        )

    # ---------------------------------------------------------
    # Stage 2: comparison
    # ---------------------------------------------------------

    for i, email in enumerate(
        remaining,
        1,
    ):

        eid = email[
            "email_id"
        ]

        cat = classified[
            eid
        ]["category"]

        if cat != "BL_COMPARISON":

            submission[eid] = {
                "category": cat,
                "status": "OK",
                "review_reason": None,
                "defect_fields": [],
                "has_defect": False,
            }

        else:

            try:

                submission[eid] = process_comparison(
                    inbox,
                    email,
                )

            except Exception as e:

                print(
                    f"[FAILED] {eid}: {e}"
                )

                _save(
                    submission,
                    partial_path,
                )

                print(
                    f"progress saved to "
                    f"{partial_path} "
                    f"({len(submission)} done). "
                    f"Fix the issue and re-run "
                    f"with --resume."
                )

                raise

        if i % 10 == 0:

            _save(
                submission,
                partial_path,
            )

            print(
                f"{len(submission)}/{len(emails)} "
                f"done (checkpoint saved)"
            )

    # ---------------------------------------------------------
    # Final save
    # ---------------------------------------------------------

    _save(
        submission,
        partial_path,
    )

    os.replace(
        partial_path,
        out_path,
    )

    print(
        f"done: wrote {out_path} "
        f"({len(submission)} entries)"
    )


def run_holdout_eval(
    source: str,
    ground_truth_path: str,
    holdout_frac: float = 0.1,
    seed: int = 42,
):
    """
    Dev-time generalization check.

    Classifies a random held-out slice and scores only that slice
    against ground truth.
    """

    inbox = Inbox(source)

    emails = list(
        inbox
    )

    with open(
        ground_truth_path,
        encoding="utf-8",
    ) as f:

        gt = json.load(f)

    rng = random.Random(
        seed
    )

    holdout_ids = set(
        rng.sample(
            [
                e["email_id"]
                for e in emails
            ],
            int(
                len(emails)
                * holdout_frac
            ),
        )
    )

    holdout = [
        e
        for e in emails
        if e["email_id"]
        in holdout_ids
    ]

    classified = classify_batch(
        holdout
    )

    correct = 0

    by_cat_total = {}
    by_cat_correct = {}

    for e in holdout:

        eid = e[
            "email_id"
        ]

        true_cat = gt[
            eid
        ]["category"]

        pred_cat = classified[
            eid
        ]["category"]

        by_cat_total[
            true_cat
        ] = (
            by_cat_total.get(
                true_cat,
                0,
            )
            + 1
        )

        if pred_cat == true_cat:

            correct += 1

            by_cat_correct[
                true_cat
            ] = (
                by_cat_correct.get(
                    true_cat,
                    0,
                )
                + 1
            )

    print(
        f"\nHoldout classification accuracy: "
        f"{correct}/{len(holdout)} = "
        f"{correct / len(holdout):.2%}\n"
    )

    for cat, total in sorted(
        by_cat_total.items()
    ):

        c = by_cat_correct.get(
            cat,
            0,
        )

        print(
            f"  {cat:16s} "
            f"{c}/{total} = "
            f"{c / total:.2%}"
        )


if __name__ == "__main__":

    import sys

    if (
        len(sys.argv) >= 2
        and sys.argv[1] == "vision_test"
    ):

        attachment = sys.argv[2]

        src = (
            sys.argv[3]
            if len(sys.argv) > 3
            else "."
        )

        vision_test(
            src,
            attachment,
        )

    elif (
        len(sys.argv) >= 2
        and sys.argv[1] == "test"
    ):

        eid = sys.argv[2]

        src = (
            sys.argv[3]
            if len(sys.argv) > 3
            else "."
        )

        process_one(
            src,
            eid,
        )

    elif (
        len(sys.argv) >= 2
        and sys.argv[1] == "holdout"
    ):

        src = (
            sys.argv[2]
            if len(sys.argv) > 2
            else "."
        )

        gt = (
            sys.argv[3]
            if len(sys.argv) > 3
            else "ground_truth.json"
        )

        run_holdout_eval(
            src,
            gt,
        )

    else:

        src = (
            sys.argv[1]
            if len(sys.argv) > 1
            else "."
        )

        limit = None

        if "--limit" in sys.argv:

            idx = sys.argv.index(
                "--limit"
            )

            if idx + 1 >= len(
                sys.argv
            ):

                raise ValueError(
                    "--limit requires a number"
                )

            limit = int(
                sys.argv[idx + 1]
            )

        resume = (
            "--resume"
            in sys.argv
        )

        only = None

        if "--only" in sys.argv:

            idx = sys.argv.index(
                "--only"
            )

            if idx + 1 >= len(
                sys.argv
            ):

                raise ValueError(
                    "--only requires comma-separated "
                    "email IDs"
                )

            only = [
                x.strip()
                for x in sys.argv[
                    idx + 1
                ].split(",")
                if x.strip()
            ]

        run(
            src,
            limit=limit,
            resume=resume,
            only=only,
        )