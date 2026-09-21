import json

with open("submission.json", "r", encoding="utf-8") as f:
    submission = json.load(f)

with open("data/ground_truth.json", "r", encoding="utf-8") as f:
    ground_truth = json.load(f)

total = 0
correct = 0
failures = []

print("=" * 60)
print("EVALUATION")
print("=" * 60)

for email_id, expected in ground_truth.items():

    # Only evaluate emails that have already been processed
    if email_id not in submission:
        continue

    total += 1
    actual = submission[email_id]

    is_correct = (
        actual.get("category") == expected.get("category")
        and actual.get("status") == expected.get("status")
        and actual.get("has_defect") == expected.get("has_defect")
        and sorted(actual.get("defect_fields", []))
            == sorted(expected.get("defect_fields", []))
    )

    if is_correct:
        correct += 1

    else:
        # Keep detailed failure information for the file
        failure_lines = []

        failure_lines.append("=" * 60)
        failure_lines.append(f"EMAIL: {email_id}")
        failure_lines.append("=" * 60)

        if actual.get("category") != expected.get("category"):
            failure_lines.append("category:")
            failure_lines.append(
                f"  expected: {expected.get('category')}"
            )
            failure_lines.append(
                f"  actual:   {actual.get('category')}"
            )

        if actual.get("status") != expected.get("status"):
            failure_lines.append("status:")
            failure_lines.append(
                f"  expected: {expected.get('status')}"
            )
            failure_lines.append(
                f"  actual:   {actual.get('status')}"
            )

        if actual.get("has_defect") != expected.get("has_defect"):
            failure_lines.append("has_defect:")
            failure_lines.append(
                f"  expected: {expected.get('has_defect')}"
            )
            failure_lines.append(
                f"  actual:   {actual.get('has_defect')}"
            )

        if (
            sorted(actual.get("defect_fields", []))
            != sorted(expected.get("defect_fields", []))
        ):
            failure_lines.append("defect_fields:")
            failure_lines.append(
                f"  expected: {expected.get('defect_fields', [])}"
            )
            failure_lines.append(
                f"  actual:   {actual.get('defect_fields', [])}"
            )

        failures.append("\n".join(failure_lines))


# Write detailed failures to file
with open("evaluation_failures.txt", "w", encoding="utf-8") as f:
    if failures:
        f.write("\n\n".join(failures))
        f.write("\n")
    else:
        f.write("No failures.\n")


# Final summary
print()
print("=" * 60)
print(f"PROCESSED: {total}")
print(f"CORRECT:   {correct}")
print(f"WRONG:     {total - correct}")

if total > 0:
    print(f"ACCURACY:  {correct / total * 100:.2f}%")

print("=" * 60)

print()
print(f"Detailed failures saved to: evaluation_failures.txt")