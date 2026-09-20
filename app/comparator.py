from extractor import FIELDS

def compare(si: dict, bl: dict) -> tuple[bool, list[str]]:
    """Returns (has_defect, defect_fields). Assumes both sides are non-null
    (call escalation.check_missing_values first)."""
    mismatches = []
    for f in FIELDS:
        a, b = si.get(f), bl.get(f)
        if f == "container_count" or f == "gross_weight_kg":
            if a is None or b is None or int(a) != int(b):
                mismatches.append(f)
        else:
            if _norm(a) != _norm(b):
                mismatches.append(f)
    return (len(mismatches) > 0, sorted(mismatches))

def _norm(s):
    if s is None:
        return None
    return " ".join(str(s).upper().split())