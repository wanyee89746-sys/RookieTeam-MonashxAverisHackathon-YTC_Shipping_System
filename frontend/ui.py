import pandas as pd
import streamlit as st

from data import fetch_report, get_comparison


CUSTOM_CSS = """
"""

CATEGORY_NAMES = {
    "BL_COMPARISON": "BL Comparison",
    "GENERAL": "General",
}

REASON_NAMES = {
    "missing_value": "Missing value",
    "unreadable": "Unreadable document",
    "extraction_failed": "Extraction failed",
}

FIELD_LABELS = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify Party",
    "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge",
    "container_count": "Container Count",
    "gross_weight_kg": "Gross Weight (kg)",
}

STATUS_BADGES = {
    "OK": "🟢 NO MISMATCH",
    "MISMATCH": "🔴 MISMATCH",
    "NEEDS_REVIEW": "🟠 NEEDS REVIEW",
    "CLASSIFIED_ONLY": "⚪ CLASSIFIED ONLY",
    "ERROR": "⚫ ERROR",
}

STATUS_OPTIONS = ["All", "OK", "MISMATCH", "NEEDS_REVIEW", "CLASSIFIED_ONLY"]


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def format_category(category):
    if not category:
        return "Unknown"
    return CATEGORY_NAMES.get(category, category.replace("_", " ").title())


def format_review_reason(reason):
    if not reason:
        return "—"
    return REASON_NAMES.get(reason, reason.replace("_", " ").title())


def display_status(item):
    """Non-comparison emails are only classified, never checked."""
    category = item.get("category")
    status = item.get("status") or "UNKNOWN"

    if category and category != "BL_COMPARISON" and status == "OK":
        return "CLASSIFIED_ONLY"

    return status


def status_badge(status):
    return STATUS_BADGES.get(status, f"⚪ {status}")


def _fmt(value):
    """Readable single-line value for display."""
    if value is None:
        return "NOT FOUND"

    text = " | ".join(
        line.strip()
        for line in str(value).splitlines()
        if line.strip()
    )

    return text or "NOT FOUND"


def _unverified_fields(report):
    results = report.get("field_results") or {}
    return [f for f, r in results.items() if r == "UNKNOWN"]


def _label(field):
    return FIELD_LABELS.get(field, field.replace("_", " ").title())


# ---------------------------------------------------------------
# Summary bar
# ---------------------------------------------------------------

def render_summary(emails):
    """Overview counts across all processed emails."""

    if not emails:
        return

    counts = {}

    for email in emails:
        s = display_status(email)
        counts[s] = counts.get(s, 0) + 1

    cols = st.columns(5)
    cols[0].metric("Total emails", len(emails))
    cols[1].metric("No mismatch", counts.get("OK", 0))
    cols[2].metric("Mismatch", counts.get("MISMATCH", 0))
    cols[3].metric("Needs review", counts.get("NEEDS_REVIEW", 0))
    cols[4].metric("Classified only", counts.get("CLASSIFIED_ONLY", 0))


# ---------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------

def render_inbox(emails):
    """Display the processed email inbox with search/filter/sort."""

    st.subheader("📥 Email Inbox")

    if not emails:
        st.info("No emails available.")
        return

    search = st.text_input(
        "Search",
        placeholder="Search email ID, subject, or sender...",
    )

    categories = sorted(
        {e.get("category") for e in emails if e.get("category")}
    )

    col_a, col_b = st.columns(2)

    with col_a:
        selected_status = st.selectbox(
            "Status",
            STATUS_OPTIONS,
            format_func=lambda s: "All" if s == "All" else status_badge(s),
        )

    with col_b:
        selected_category = st.selectbox(
            "Category",
            ["All"] + categories,
            format_func=lambda c: "All" if c == "All" else format_category(c),
        )

    sort_by = st.selectbox(
        "Sort by",
        ["Email ID", "Subject", "Status"],
    )

    filtered = emails

    if search:
        q = search.lower()
        filtered = [
            e for e in filtered
            if q in str(e.get("email_id", "")).lower()
            or q in str(e.get("subject", "")).lower()
            or q in str(e.get("from", "")).lower()
        ]

    if selected_status != "All":
        filtered = [
            e for e in filtered
            if display_status(e) == selected_status
        ]

    if selected_category != "All":
        filtered = [
            e for e in filtered
            if e.get("category") == selected_category
        ]

    if sort_by == "Email ID":
        filtered = sorted(filtered, key=lambda e: e.get("email_id", ""))
    elif sort_by == "Subject":
        filtered = sorted(
            filtered, key=lambda e: str(e.get("subject", "")).lower()
        )
    elif sort_by == "Status":
        filtered = sorted(filtered, key=display_status)

    st.caption(f"Showing {len(filtered)} of {len(emails)} emails")

    if not filtered:
        st.info("No emails match your search/filter.")
        return

    selected_id = st.session_state.get("selected_email_id")

    for email in filtered:
        email_id = email.get("email_id", "")
        subject = email.get("subject", "(No subject)")
        sender = email.get("from", "(Unknown sender)")
        category = email.get("category")

        if st.button(
            f"{email_id} — {subject}",
            key=f"email_{email_id}",
            use_container_width=True,
            type="primary" if email_id == selected_id else "secondary",
        ):
            st.session_state.selected_email_id = email_id
            st.rerun()

        cat_text = f"{format_category(category)}  |  " if category else ""

        st.caption(
            f"From: {sender}  |  {cat_text}"
            f"{status_badge(display_status(email))}"
        )


# ---------------------------------------------------------------
# Report
# ---------------------------------------------------------------

def render_report(email):
    """Display the already-processed verification report."""

    if not email:
        st.info("Select an email from the inbox.")
        return

    email_id = email.get("email_id", "")

    st.subheader("📄 Verification Report")
    st.markdown(f"**Email ID:** `{email_id}`")
    st.markdown(f"**Subject:** {email.get('subject', '—')}")
    st.markdown(f"**From:** {email.get('from', '—')}")

    st.divider()

    report = fetch_report(email_id)

    if not report:
        st.warning("No verification report available for this email.")
        return

    status = display_status(report)
    category = report.get("category")
    reason = report.get("review_reason")
    defect_fields = report.get("defect_fields") or []
    unverified = _unverified_fields(report)
    comparison = get_comparison(report)

    st.markdown(f"### Status: {status_badge(status)}")

    # Non-comparison emails stop here.
    if status == "CLASSIFIED_ONLY":
        st.info(
            f"Classified as **{format_category(category)}**. "
            "Only BL comparison requests go through the document check."
        )
        return

    if status == "MISMATCH":
        st.error(f"{len(defect_fields)} mismatch(es) found. See details below.")

    elif status == "NEEDS_REVIEW":
        st.warning(f"Human review required: {format_review_reason(reason)}")

    elif status == "OK":
        if unverified:
            st.warning(
                "No mismatch detected in the checked fields, but these "
                "could not be verified: "
                + ", ".join(_label(f) for f in unverified)
            )
        else:
            st.success("No mismatch detected. All 7 fields match.")

    col1, col2, col3 = st.columns(3)
    col1.metric("Category", format_category(category))
    col2.metric("Mismatches", len(defect_fields))
    col3.metric("Unverified fields", len(unverified))

    _render_issues(defect_fields, comparison)
    _render_comparison_table(report, comparison)


def _render_issues(defect_fields, comparison):
    if not defect_fields:
        return

    st.markdown("### ⚠️ Issues Detected")

    for field in defect_fields:
        if field in comparison:
            si, bl = comparison[field]
            st.write(
                f"• **{_label(field)}** — "
                f"SI: `{_fmt(si)}` / BL: `{_fmt(bl)}`"
            )
        else:
            st.write(f"• **{_label(field)}**")


def _highlight_row(row):
    colors = {
        "❌ MISMATCH": "background-color: rgba(220, 53, 69, 0.18)",
        "⚠️ UNVERIFIED": "background-color: rgba(255, 165, 0, 0.18)",
    }
    return [colors.get(row["RESULT"], "")] * len(row)


def _render_comparison_table(report, comparison):
    """Always show all 7 fields side by side for BL comparison emails."""

    st.markdown("### Field Comparison")

    defect_fields = set(report.get("defect_fields") or [])
    field_results = report.get("field_results") or {}
    has_values = bool(comparison)

    rows = []

    for field in FIELD_LABELS:
        si_value, bl_value = comparison.get(field, (None, None))
        outcome = field_results.get(field)

        if field in defect_fields or outcome == "MISMATCH":
            result = "❌ MISMATCH"
        elif outcome == "UNKNOWN":
            result = "⚠️ UNVERIFIED"
        elif outcome == "MATCH":
            result = "✅ MATCH"
        else:
            result = "—"

        rows.append(
            {
                "FIELD": _label(field),
                "SI VALUE": _fmt(si_value) if has_values else "—",
                "BL VALUE": _fmt(bl_value) if has_values else "—",
                "RESULT": result,
            }
        )

    st.dataframe(
        pd.DataFrame(rows).style.apply(_highlight_row, axis=1),
        hide_index=True,
        use_container_width=True,
    )

    if not has_values:
        st.caption(
            "SI/BL values were not saved for this email. "
            "Re-run the pipeline for it to see them."
        )