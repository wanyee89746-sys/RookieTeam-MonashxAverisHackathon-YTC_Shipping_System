import json
import os
import sys


# =========================================================
# PROJECT PATH SETUP
# =========================================================

PROJECT_ROOT = os.path.dirname(
    os.path.abspath(__file__)
)

APP_DIR = os.path.join(
    PROJECT_ROOT,
    "app",
)

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


# =========================================================
# YOUR EXISTING DATA STRUCTURE
# =========================================================

# project/
# ├── app/
# │   ├── loader.py
# │   ├── pipeline.py
# │   ├── extractor.py
# │   ├── comparator.py
# │   └── ...
# │
# ├── data/
# │   ├── ground_truth.json
# │   ├── inbox/
# │   │   ├── email_001
# │   │   ├── email_002
# │   │   └── ...
# │   └── attachments/
# │       ├── 001/
# │       ├── 002/
# │       └── ...
# │
# ├── submission.json
# └── debug_wrong_cases.py


GROUND_TRUTH_FILE = os.path.join(
    PROJECT_ROOT,
    "data",
    "ground_truth.json",
)

SUBMISSION_FILE = os.path.join(
    PROJECT_ROOT,
    "submission.json",
)

# IMPORTANT:
# Your loader should receive "data", because it contains
# both inbox/ and attachments/.
SOURCE = os.path.join(
    PROJECT_ROOT,
    "data",
)


# =========================================================
# WRONG CASES
# =========================================================

WRONG_CASES = [
    "email_032",
    "email_055",
    "email_097",
    "email_107",
    "email_121",
    "email_133",
    "email_198",
    "email_256",
    "email_291",
    "email_302",
    "email_354",
    "email_361",
    "email_383",
    "email_417",
    "email_435",
    "email_455",
    "email_462",
    "email_481",
    "email_483",
    "email_498",
    "email_516",
    "email_517",
    "email_518",
    "email_519",
    "email_520",
]


# =========================================================
# FIELDS
# =========================================================

FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]


# =========================================================
# JSON
# =========================================================

def load_json(path):
    """Load a JSON file."""

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def print_value(value):
    """Print a value in a readable form."""

    if value is None:
        return "None"

    if isinstance(value, list):
        if not value:
            return "[]"

        return "[" + ", ".join(
            str(x) for x in value
        ) + "]"

    return str(value)


# =========================================================
# RESULT PRINTING
# =========================================================

def print_result_section(
    title,
    result,
):
    """Print expected or actual result."""

    print()
    print(f"{title}:")

    print(
        f"  category      = "
        f"{print_value(result.get('category'))}"
    )

    print(
        f"  status        = "
        f"{print_value(result.get('status'))}"
    )

    print(
        f"  review_reason = "
        f"{print_value(result.get('review_reason'))}"
    )

    print(
        f"  defect_fields = "
        f"{print_value(result.get('defect_fields'))}"
    )

    print(
        f"  has_defect    = "
        f"{print_value(result.get('has_defect'))}"
    )


# =========================================================
# EMAIL INFORMATION
# =========================================================

def print_email_info(email):
    """
    Print information useful for diagnosing
    classification errors.
    """

    print()
    print("EMAIL INFORMATION:")

    subject = (
        email.get("subject")
        or email.get("title")
        or email.get("email_subject")
    )

    sender = (
        email.get("sender")
        or email.get("from")
        or email.get("from_address")
        or email.get("email_from")
    )

    body = (
        email.get("body")
        or email.get("text")
        or email.get("content")
        or ""
    )

    print(
        f"  sender  = "
        f"{print_value(sender)}"
    )

    print(
        f"  subject = "
        f"{print_value(subject)}"
    )

    print()
    print("  body:")

    if body:
        print(
            "  "
            + str(body).replace(
                "\n",
                "\n  ",
            )
        )
    else:
        print("  None")


# =========================================================
# ATTACHMENTS
# =========================================================

def print_attachments(email):
    """Print attachment paths."""

    attachments = email.get(
        "attachments",
        [],
    )

    print()
    print("ATTACHMENTS:")

    if not attachments:
        print("  None")
        return

    for attachment in attachments:
        print(
            f"  - {attachment}"
        )


# =========================================================
# ATTACHMENT TEXT
# =========================================================

def read_attachment_text(
    inbox,
    path,
):
    """
    Use the project's existing attachment
    reader from pipeline.py.
    """

    try:
        from pipeline import (
            read_attachment_text,
        )

        return read_attachment_text(
            inbox,
            path,
        )

    except Exception as e:
        print(
            f"  [READ ERROR] "
            f"{path}: {e}"
        )
        return None


# =========================================================
# PRINT EXTRACTED FIELDS
# =========================================================

def print_fields(
    label,
    fields,
):
    """Print extracted SI/BL fields."""

    print()
    print(
        f"{label} EXTRACTED FIELDS:"
    )

    if fields is None:
        print(
            "  EXTRACTION RESULT = None"
        )
        return

    for field in FIELDS:
        print(
            f"  {field:20s}= "
            f"{print_value(fields.get(field))}"
        )


# =========================================================
# DIAGNOSE ONE CASE
# =========================================================

def diagnose_case(
    inbox,
    email,
    ground_truth,
    submission,
):
    """Diagnose one wrong email."""

    email_id = email.get(
        "email_id"
    )

    print()
    print("=" * 80)
    print(
        f"WRONG CASE: {email_id}"
    )
    print("=" * 80)

    # -----------------------------------------------------
    # EXPECTED / ACTUAL
    # -----------------------------------------------------

    expected = ground_truth.get(
        email_id,
        {},
    )

    actual = submission.get(
        email_id,
        {},
    )

    print_result_section(
        "EXPECTED",
        expected,
    )

    print_result_section(
        "ACTUAL",
        actual,
    )

    # -----------------------------------------------------
    # EMAIL INFORMATION
    # -----------------------------------------------------

    print_email_info(email)

    # -----------------------------------------------------
    # ATTACHMENTS
    # -----------------------------------------------------

    print_attachments(email)

    # -----------------------------------------------------
    # CLASSIFICATION-ONLY CASE
    # -----------------------------------------------------

    expected_category = expected.get(
        "category"
    )

    actual_category = actual.get(
        "category"
    )

    if (
        expected_category != "BL_COMPARISON"
        and actual_category != "BL_COMPARISON"
    ):
        print()
        print("DIAGNOSIS:")
        print(
            "  This is a classification case."
        )
        print(
            "  No SI/BL comparison is needed."
        )
        return

    # -----------------------------------------------------
    # FIND SI / BL ATTACHMENTS
    # -----------------------------------------------------

    attachments = email.get(
        "attachments",
        [],
    )

    si_path = next(
        (
            a
            for a in attachments
            if "_SI" in str(a)
        ),
        None,
    )

    bl_path = next(
        (
            a
            for a in attachments
            if "_BL" in str(a)
        ),
        None,
    )

    print()
    print("DOCUMENT PATHS:")

    print(
        f"  SI = {si_path}"
    )

    print(
        f"  BL = {bl_path}"
    )

    # -----------------------------------------------------
    # READ SI
    # -----------------------------------------------------

    si_text = None

    if si_path:
        si_text = read_attachment_text(
            inbox,
            si_path,
        )

    # -----------------------------------------------------
    # READ BL
    # -----------------------------------------------------

    bl_text = None

    if bl_path:
        bl_text = read_attachment_text(
            inbox,
            bl_path,
        )

    # -----------------------------------------------------
    # DOCUMENT TEXT
    # -----------------------------------------------------

    print()
    print("SI TEXT:")

    if si_text:
        print(str(si_text))
    else:
        print("None")

    print()
    print("BL TEXT:")

    if bl_text:
        print(str(bl_text))
    else:
        print("None")

    # -----------------------------------------------------
    # CURRENT EXTRACTOR
    # -----------------------------------------------------

    try:
        from extractor import (
            extract_fields,
        )

    except Exception as e:
        print()
        print(
            "[ERROR] Could not import "
            f"extractor: {e}"
        )
        return

    print()
    print(
        "RUNNING CURRENT EXTRACTOR..."
    )

    try:
        si_fields = (
            extract_fields(si_text)
            if si_text
            else None
        )

    except Exception as e:
        print(
            f"[SI EXTRACTION ERROR] "
            f"{e}"
        )
        si_fields = None

    try:
        bl_fields = (
            extract_fields(bl_text)
            if bl_text
            else None
        )

    except Exception as e:
        print(
            f"[BL EXTRACTION ERROR] "
            f"{e}"
        )
        bl_fields = None

    # -----------------------------------------------------
    # EXTRACTED FIELDS
    # -----------------------------------------------------

    print_fields(
        "SI",
        si_fields,
    )

    print_fields(
        "BL",
        bl_fields,
    )

    # -----------------------------------------------------
    # CURRENT COMPARATOR
    # -----------------------------------------------------

    if (
        si_fields is not None
        and bl_fields is not None
    ):
        try:
            from comparator import (
                compare,
            )

            has_defect, defects = compare(
                si_fields,
                bl_fields,
            )

            print()
            print(
                "CURRENT COMPARATOR RESULT:"
            )

            print(
                f"  has_defect    = "
                f"{has_defect}"
            )

            print(
                f"  defect_fields = "
                f"{defects}"
            )

        except Exception as e:
            print()
            print(
                f"[COMPARATOR ERROR] "
                f"{e}"
            )

    # -----------------------------------------------------
    # CURRENT ESCALATION
    # -----------------------------------------------------

    try:
        from escalation import (
            check_review,
        )

        review_reason = check_review(
            email,
            si_text,
            bl_text,
            si_fields,
            bl_fields,
        )

        print()
        print(
            "CURRENT ESCALATION RESULT:"
        )

        print(
            f"  review_reason = "
            f"{review_reason}"
        )

    except Exception as e:
        print()
        print(
            f"[ESCALATION ERROR] "
            f"{e}"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 80)
    print(
        "WRONG CASE DEEP DEBUGGER"
    )
    print("=" * 80)

    print()
    print(
        f"Project root : {PROJECT_ROOT}"
    )

    print(
        f"App folder   : {APP_DIR}"
    )

    print(
        f"Data folder  : {SOURCE}"
    )

    print(
        f"Ground truth : "
        f"{GROUND_TRUTH_FILE}"
    )

    print(
        f"Submission   : "
        f"{SUBMISSION_FILE}"
    )

    # -----------------------------------------------------
    # CHECK IMPORTANT PATHS
    # -----------------------------------------------------

    print()
    print("PATH CHECK:")

    print(
        f"  app/loader.py       : "
        f"{os.path.exists(os.path.join(APP_DIR, 'loader.py'))}"
    )

    print(
        f"  data/inbox/         : "
        f"{os.path.exists(os.path.join(SOURCE, 'inbox'))}"
    )

    print(
        f"  data/attachments/   : "
        f"{os.path.exists(os.path.join(SOURCE, 'attachments'))}"
    )

    print(
        f"  ground_truth.json   : "
        f"{os.path.exists(GROUND_TRUTH_FILE)}"
    )

    print(
        f"  submission.json     : "
        f"{os.path.exists(SUBMISSION_FILE)}"
    )

    # -----------------------------------------------------
    # LOAD GROUND TRUTH
    # -----------------------------------------------------

    try:
        ground_truth = load_json(
            GROUND_TRUTH_FILE
        )

    except Exception as e:
        print()
        print(
            f"ERROR loading ground truth: "
            f"{e}"
        )
        return

    # -----------------------------------------------------
    # LOAD SUBMISSION
    # -----------------------------------------------------

    try:
        submission = load_json(
            SUBMISSION_FILE
        )

    except Exception as e:
        print()
        print(
            f"ERROR loading submission: "
            f"{e}"
        )
        return

    # -----------------------------------------------------
    # IMPORT LOADER
    # -----------------------------------------------------

    try:
        from loader import Inbox

    except Exception as e:
        print()
        print(
            f"ERROR importing Inbox: "
            f"{e}"
        )
        return

    # -----------------------------------------------------
    # CREATE INBOX
    # -----------------------------------------------------

    try:
        inbox = Inbox(
            SOURCE
        )

    except Exception as e:
        print()
        print(
            f"ERROR creating Inbox: "
            f"{e}"
        )
        return

    # -----------------------------------------------------
    # PROCESS WRONG CASES
    # -----------------------------------------------------

    print()
    print(
        f"Cases to inspect: "
        f"{len(WRONG_CASES)}"
    )

    for email_id in WRONG_CASES:

        try:
            email = inbox.get(
                email_id
            )

        except Exception as e:
            print()
            print("=" * 80)
            print(
                f"WRONG CASE: "
                f"{email_id}"
            )
            print("=" * 80)
            print(
                f"[ERROR] Could not load "
                f"email: {e}"
            )
            continue

        diagnose_case(
            inbox,
            email,
            ground_truth,
            submission,
        )

    # -----------------------------------------------------
    # END
    # -----------------------------------------------------

    print()
    print("=" * 80)
    print(
        "END OF DEBUG OUTPUT"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
