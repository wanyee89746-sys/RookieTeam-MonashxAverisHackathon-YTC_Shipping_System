import json

with open("submission.json", "r", encoding="utf-8") as f:
    submission = json.load(f)

with open("data/ground_truth.json", "r", encoding="utf-8") as f:
    ground_truth = json.load(f)

total = 0
correct = 0

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
        print(f"✅ {email_id}")
    else:
        print(f"❌ {email_id}")

        if actual.get("category") != expected.get("category"):
            print(f"   category:")
            print(f"      expected: {expected.get('category')}")
            print(f"      actual:   {actual.get('category')}")

        if actual.get("status") != expected.get("status"):
            print(f"   status:")
            print(f"      expected: {expected.get('status')}")
            print(f"      actual:   {actual.get('status')}")

        if actual.get("has_defect") != expected.get("has_defect"):
            print(f"   has_defect:")
            print(f"      expected: {expected.get('has_defect')}")
            print(f"      actual:   {actual.get('has_defect')}")

        if sorted(actual.get("defect_fields", [])) != sorted(expected.get("defect_fields", [])):
            print(f"   defect_fields:")
            print(f"      expected: {expected.get('defect_fields', [])}")
            print(f"      actual:   {actual.get('defect_fields', [])}")

print()
print("=" * 60)
print(f"PROCESSED: {total}")
print(f"CORRECT:   {correct}")
print(f"WRONG:     {total - correct}")

if total > 0:
    print(f"ACCURACY:  {correct / total * 100:.2f}%")

print("=" * 60)