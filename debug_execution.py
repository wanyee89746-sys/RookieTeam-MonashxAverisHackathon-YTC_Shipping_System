import sys
import os
import json

# Make app/ and data/ importable
sys.path.insert(0, os.path.abspath("app"))
sys.path.insert(0, os.path.abspath("data"))

from loader import Inbox
from pipeline import read_attachment_text
from extractor import extract_fields
from escalation import check_review
from comparator import compare

SOURCE = "data"
OUTPUT_FILE = "debug_output.txt"

IDS = [
    "044", "051", "052", "064", "107", "113", "118", "119",
    "121", "133", "143", "144", "145", "146", "167", "174",
    "178", "182", "197", "227", "235", "243", "256", "275",
    "291", "296", "300", "307", "335", "348", "361", "379",
    "383", "398", "408", "417", "435", "455", "468", "481",
    "483", "491", "520"
]


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def compact_fields(fields):
    if fields is None:
        return None

    return {
        key: value
        for key, value in fields.items()
        if value is not None
    }


with open(OUTPUT_FILE, "w", encoding="utf-8") as output:
    original_stdout = sys.stdout
    sys.stdout = Tee(original_stdout, output)

    try:
        print("=" * 70)
        print("COMPACT DEBUG OUTPUT")
        print("=" * 70)

        inbox = Inbox(SOURCE)

        for email in inbox:
            eid = email["email_id"]

            if eid not in IDS:
                continue

            print("\n" + "=" * 70)
            print(eid)
            print("=" * 70)

            print("SUBJECT:")
            print(email.get("subject", "").strip())

            attachments = email.get("attachments", [])

            si_path = next(
                (a for a in attachments if "_SI" in a),
                None
            )

            bl_path = next(
                (a for a in attachments if "_BL" in a),
                None
            )

            print("\nFILES:")
            print("SI:", si_path)
            print("BL:", bl_path)

            # Read documents
            si_text = (
                read_attachment_text(inbox, si_path)
                if si_path
                else None
            )

            bl_text = (
                read_attachment_text(inbox, bl_path)
                if bl_path
                else None
            )

            # Extract fields
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

            print("\nSI FIELDS:")
            print(json.dumps(
                compact_fields(si_fields),
                ensure_ascii=False
            ))

            print("\nBL FIELDS:")
            print(json.dumps(
                compact_fields(bl_fields),
                ensure_ascii=False
            ))

            # Review
            reason = check_review(
                email,
                si_text,
                bl_text,
                si_fields,
                bl_fields,
            )

            print("\nREVIEW:")
            print(reason)

            # Comparison
            if si_fields and bl_fields:
                mismatch, fields = compare(
                    si_fields,
                    bl_fields
                )

                print("\nCOMPARISON:")
                print("Mismatch:", mismatch)
                print("Fields:", fields)

                # Show only values for mismatched fields
                if fields:
                    print("\nMISMATCH DETAILS:")

                    for field in fields:
                        print(
                            f"{field}: "
                            f"SI={si_fields.get(field)!r} | "
                            f"BL={bl_fields.get(field)!r}"
                        )

            else:
                print("\nCOMPARISON:")
                print("Skipped - missing extracted fields")

        print("\n" + "=" * 70)
        print("DEBUG COMPLETE")
        print("=" * 70)

    finally:
        sys.stdout = original_stdout

print(f"Debug output saved to: {os.path.abspath(OUTPUT_FILE)}")