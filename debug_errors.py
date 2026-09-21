import json
import os


# ---------------------------------------------------------
# FILE LOCATIONS
# ---------------------------------------------------------
# Keep your existing file locations.
GROUND_TRUTH_FILE = os.path.join("data", "ground_truth.json")
SUBMISSION_FILE = "submission.json"


def load_json(path):
    """Load a JSON file and return its contents."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_case(email_id, expected, actual):
    """
    Compare one email's expected result with the actual result.

    Returns a list of field-level differences.
    """
    differences = []

    fields = [
        "category",
        "status",
        "review_reason",
        "defect_fields",
        "has_defect",
    ]

    for field in fields:
        expected_value = expected.get(field)
        actual_value = actual.get(field)

        # Order of defect_fields should not matter.
        if field == "defect_fields":
            expected_value = sorted(expected_value or [])
            actual_value = sorted(actual_value or [])

        if expected_value != actual_value:
            differences.append(
                {
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )

    return differences


def print_value(value):
    """Print values in a compact readable format."""
    if value is None:
        return "None"

    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + ", ".join(str(x) for x in value) + "]"

    return str(value)


def print_case(email_id, differences):
    """Print one wrong case."""
    print()
    print("=" * 72)
    print(f"WRONG CASE: {email_id}")
    print("=" * 72)

    for diff in differences:
        print(f"\n{diff['field']}:")
        print(f"  expected = {print_value(diff['expected'])}")
        print(f"  actual   = {print_value(diff['actual'])}")


def summarize_errors(all_differences):
    """Print a summary of which output fields are wrong."""
    field_counts = {}

    for differences in all_differences.values():
        for diff in differences:
            field = diff["field"]
            field_counts[field] = field_counts.get(field, 0) + 1

    print()
    print("=" * 72)
    print("ERROR SUMMARY")
    print("=" * 72)

    for field, count in sorted(
        field_counts.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"{field:20s}: {count}")


def main():
    print("=" * 72)
    print("GROUND TRUTH vs SUBMISSION DEBUGGER")
    print("=" * 72)

    print(f"\nGround truth : {GROUND_TRUTH_FILE}")
    print(f"Submission   : {SUBMISSION_FILE}")

    # ---------------------------------------------------------
    # LOAD FILES
    # ---------------------------------------------------------
    try:
        ground_truth = load_json(GROUND_TRUTH_FILE)
        submission = load_json(SUBMISSION_FILE)
    except Exception as e:
        print(f"\nERROR: {e}")
        return

    if not isinstance(ground_truth, dict):
        print("\nERROR: ground_truth.json is not a JSON object.")
        return

    if not isinstance(submission, dict):
        print("\nERROR: submission.json is not a JSON object.")
        return

    # ---------------------------------------------------------
    # BASIC FILE INFORMATION
    # ---------------------------------------------------------
    gt_ids = set(ground_truth.keys())
    submission_ids = set(submission.keys())

    missing_from_submission = gt_ids - submission_ids
    extra_in_submission = submission_ids - gt_ids

    print(f"\nGround truth cases : {len(gt_ids)}")
    print(f"Submission cases   : {len(submission_ids)}")

    if missing_from_submission:
        print(
            f"\nWARNING: {len(missing_from_submission)} "
            "cases are missing from submission.json"
        )
        print("Missing IDs:")

        for email_id in sorted(missing_from_submission):
            print(f"  {email_id}")

    if extra_in_submission:
        print(
            f"\nWARNING: {len(extra_in_submission)} "
            "extra cases exist in submission.json"
        )
        print("Extra IDs:")

        for email_id in sorted(extra_in_submission):
            print(f"  {email_id}")

    # ---------------------------------------------------------
    # COMPARE COMMON CASES
    # ---------------------------------------------------------
    common_ids = sorted(gt_ids & submission_ids)

    wrong_cases = {}
    correct_count = 0

    for email_id in common_ids:
        expected = ground_truth[email_id]
        actual = submission[email_id]

        differences = compare_case(
            email_id,
            expected,
            actual,
        )

        if differences:
            wrong_cases[email_id] = differences
        else:
            correct_count += 1

    # ---------------------------------------------------------
    # MAIN RESULT
    # ---------------------------------------------------------
    total_expected = len(gt_ids)

    print()
    print("=" * 72)
    print("RESULT")
    print("=" * 72)

    print(f"Correct common cases : {correct_count}")
    print(f"Wrong common cases   : {len(wrong_cases)}")
    print(f"Total ground truth   : {total_expected}")

    if total_expected > 0:
        accuracy = correct_count / total_expected
        print(f"Accuracy             : {accuracy:.2%}")

    # ---------------------------------------------------------
    # WRONG CASES
    # ---------------------------------------------------------
    if not wrong_cases:
        print("\nNo differences found.")
        print("submission.json matches ground_truth.json.")
        return

    print()
    print("=" * 72)
    print(f"WRONG CASES ({len(wrong_cases)})")
    print("=" * 72)

    for email_id, differences in wrong_cases.items():
        print_case(email_id, differences)

    # ---------------------------------------------------------
    # ERROR SUMMARY
    # ---------------------------------------------------------
    summarize_errors(wrong_cases)

    # ---------------------------------------------------------
    # ERROR PATTERN SUMMARY
    # ---------------------------------------------------------
    print()
    print("=" * 72)
    print("ERROR PATTERN SUMMARY")
    print("=" * 72)

    category_errors = 0
    status_errors = 0
    review_reason_errors = 0
    defect_field_errors = 0
    has_defect_errors = 0

    for differences in wrong_cases.values():
        fields = {diff["field"] for diff in differences}

        if "category" in fields:
            category_errors += 1

        if "status" in fields:
            status_errors += 1

        if "review_reason" in fields:
            review_reason_errors += 1

        if "defect_fields" in fields:
            defect_field_errors += 1

        if "has_defect" in fields:
            has_defect_errors += 1

    print(f"Category errors      : {category_errors}")
    print(f"Status errors        : {status_errors}")
    print(f"Review reason errors : {review_reason_errors}")
    print(f"Defect field errors  : {defect_field_errors}")
    print(f"Has-defect errors    : {has_defect_errors}")

    # ---------------------------------------------------------
    # WRONG EMAIL IDS
    # ---------------------------------------------------------
    print()
    print("=" * 72)
    print("WRONG EMAIL IDS")
    print("=" * 72)

    print(", ".join(sorted(wrong_cases.keys())))


if __name__ == "__main__":
    main()
