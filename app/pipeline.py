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
    path: str
) -> str | None:
    """
    Return plain text for an attachment.

    For normal PDFs, use the existing text extraction.

    If a PDF contains no usable text, fall back to Gemini Vision:
        PDF -> rendered page image -> Gemini Vision -> structured text

    The Vision path is only a fallback. It does not replace the
    existing extraction path that currently achieves 520/520.
    """

    try:
        raw = inbox.read_bytes(path)

    except Exception:
        return None

    if not raw:
        return None

    if path.endswith(".txt"):
        return raw.decode(
            "utf-8",
            errors="replace",
        )

    if path.endswith(".pdf"):
        text = _pdf_text(raw)

        if text:
            return text

        # -----------------------------------------------------
        # Advanced fallback:
        # scanned/image-only PDF -> Gemini Vision
        # -----------------------------------------------------

        print(
            f"[VISION] No readable PDF text: {path}",
            flush=True,
        )

        return _pdf_vision_text(raw, path)

    if path.endswith(".docx"):
        return _docx_text(raw)

    if path.endswith(".xlsx"):
        return _xlsx_text(raw)

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
    Render a PDF page as an image and ask Gemini Vision
    to extract the seven shipping fields.

    Returns the fields as ordinary labelled text so the
    existing extract_fields() function can process them.

    No temporary image files are created.
    """

    import io

    from dotenv import load_dotenv
    from PIL import Image
    import pymupdf
    from google import genai

    try:

        # -----------------------------------------------------
        # Load Gemini API key
        # -----------------------------------------------------

        load_dotenv(
            os.path.join(
                os.path.dirname(__file__),
                ".env",
            )
        )

        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            print(
                "[VISION] GEMINI_API_KEY not found",
                flush=True,
            )
            return None

        print(
            "[VISION] GEMINI_API_KEY found",
            flush=True,
        )

        # -----------------------------------------------------
        # Open PDF directly from memory
        # -----------------------------------------------------

        doc = pymupdf.open(
            stream=raw,
            filetype="pdf",
        )

        if len(doc) == 0:
            print(
                f"[VISION] PDF has no pages: {path}",
                flush=True,
            )
            return None

        # -----------------------------------------------------
        # Render pages in memory.
        #
        # Most shipping documents are one or a few pages.
        # Limit to the first 5 pages to avoid excessive
        # multimodal requests.
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
                f"[VISION] Gemini returned no text: {path}",
                flush=True,
            )
            return None

        print(
            f"[VISION] Successfully extracted: {path}",
            flush=True,
        )

        return text

    except Exception as e:

        print(
            f"[VISION] Failed for {path}: "
            f"{type(e).__name__}: {e}",
            flush=True,
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
    email: dict
) -> dict:
    """
    Runs extraction/comparison/escalation for an email that has
    ALREADY been classified as BL_COMPARISON.

    Extraction may use Gemini when local extraction is uncertain.

    Comparison itself is deterministic.
    """

    result = {
        "category": "BL_COMPARISON",
        "status": "OK",
        "review_reason": None,
        "defect_fields": [],
        "has_defect": False,
    }

    atts = email.get(
        "attachments",
        [],
    )

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

    si_text = (
        read_attachment_text(
            inbox,
            si_path,
        )
        if si_path
        else None
    )

    bl_text = (
        read_attachment_text(
            inbox,
            bl_path,
        )
        if bl_path
        else None
    )

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

    # Keep detailed field-level information.
    #
    # field_results preserves the existing comparison result.
    result["field_results"] = detailed["field_results"]

    # Store the actual SI and BL values so the final report
    # can show them side-by-side.
    result["field_values"] = detailed["field_values"]

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

    print("\n===== VISION TEST RESULT =====")

    if result:
        print(result)
    else:
        print("Vision extraction failed.")

    return result


def process_one(
    source: str,
    email_id: str
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

    print("\n" + "=" * 80)
    print("SHIPPING DOCUMENT VERIFICATION")
    print("=" * 80)

    print(f"Email ID: {email_id}")
    print(f"Category: {result['category']}")
    print(f"Status:   {result['status']}")

    if result.get("review_reason"):
        print(
            f"Review reason: "
            f"{result['review_reason']}"
        )

    if result.get("field_values"):

        print("\n" + "-" * 80)
        print(
            f"{'FIELD':<24}"
            f"{'SI VALUE':<26}"
            f"{'BL VALUE':<26}"
            f"RESULT"
        )
        print("-" * 80)

        field_labels = {
            "shipper": "Shipper",
            "consignee": "Consignee",
            "notify_party": "Notify Party",
            "port_of_loading": "Port of Loading",
            "port_of_discharge": "Port of Discharge",
            "container_count": "Container Count",
            "gross_weight_kg": "Gross Weight (kg)",
        }

        for field, values in result["field_values"].items():

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
            ].get(field, "UNKNOWN")

            print(
                f"{field_labels.get(field, field):<24}"
                f"{si_value[:25]:<26}"
                f"{bl_value[:25]:<26}"
                f"{comparison}"
            )

        print("-" * 80)

    if result["status"] == "OK":
        print("\nNo mismatch detected.")

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


def run(
    source: str,
    out_path: str = "submission.json",
    limit: int | None = None,
):

    inbox = Inbox(source)

    emails = list(
        inbox
    )

    # ---------------------------------------------------------
    # Resume
    # ---------------------------------------------------------

    submission = {}

    if os.path.exists(
        out_path
    ):

        with open(
            out_path,
            encoding="utf-8",
        ) as f:

            submission = json.load(f)

        print(
            f"resuming: {len(submission)} already done, "
            f"skipping those"
        )

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
        f"left to process"
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

                with open(
                    out_path,
                    "w",
                    encoding="utf-8",
                ) as f:

                    json.dump(
                        submission,
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )

                print(
                    f"progress saved to "
                    f"{out_path} "
                    f"({len(submission)} done). "
                    f"Fix the issue and re-run."
                )

                raise

        if i % 10 == 0:

            with open(
                out_path,
                "w",
                encoding="utf-8",
            ) as f:

                json.dump(
                    submission,
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            print(
                f"{len(submission)}/{len(emails)} "
                f"done (checkpoint saved)"
            )

    # ---------------------------------------------------------
    # Final save
    # ---------------------------------------------------------

    with open(
        out_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            submission,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"done: wrote {out_path}"
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
                0
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
                    0
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
            0
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

        run(
            src,
            limit=limit,
        )