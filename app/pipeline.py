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
    """Return plain text for an attachment, or None if unreadable/empty."""

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

    # Keep detailed field-level information for debugging.
    #
    # This does not change the main submission fields above.
    result["field_results"] = detailed["field_results"]

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

    print(
        json.dumps(
            {
                email_id: result
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    return result


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