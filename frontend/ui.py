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


def format_category(category):
    return CATEGORY_NAMES.get(
        category,
        category or "Unknown",
    )


def format_status(status):
    return status or "Unknown"


def format_review_reason(reason):
    if not reason:
        return "—"

    return REASON_NAMES.get(
        reason,
        reason.replace("_", " ").title(),
    )


def status_badge(status):
    status = status or "UNKNOWN"

    if status == "OK":
        return "🟢 OK"

    if status == "MISMATCH":
        return "🔴 MISMATCH"

    if status == "NEEDS_REVIEW":
        return "🟠 NEEDS REVIEW"

    return f"⚪ {status}"


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

    status_options = [
        "All",
        "OK",
        "MISMATCH",
        "NEEDS_REVIEW",
    ]

    selected_status = st.selectbox(
        "Status",
        status_options,
    )

    sort_options = [
        "Email ID",
        "Subject",
        "Status",
    ]

    sort_by = st.selectbox(
        "Sort by",
        sort_options,
    )

    filtered = emails

    # Search by email ID, subject, or sender.
    if search:
        search_lower = search.lower()

        filtered = [
            email
            for email in filtered
            if search_lower
            in str(
                email.get("email_id", "")
            ).lower()
            or search_lower
            in str(
                email.get("subject", "")
            ).lower()
            or search_lower
            in str(
                email.get("from", "")
            ).lower()
        ]

    # Filter by verification status.
    if selected_status != "All":
        filtered = [
            email
            for email in filtered
            if email.get("status") == selected_status
        ]

    # Sort the processed results.
    if sort_by == "Email ID":
        filtered = sorted(
            filtered,
            key=lambda email: email.get(
                "email_id",
                "",
            ),
        )

    elif sort_by == "Subject":
        filtered = sorted(
            filtered,
            key=lambda email: email.get(
                "subject",
                "",
            ).lower(),
        )

    elif sort_by == "Status":
        filtered = sorted(
            filtered,
            key=lambda email: email.get(
                "status",
                "",
            ),
        )

    st.caption(
        f"Showing {len(filtered)} of {len(emails)} emails"
    )

    if not filtered:
        st.info("No emails match your search/filter.")
        return

    for email in filtered:
        email_id = email.get(
            "email_id",
            "",
        )

        subject = email.get(
            "subject",
            "(No subject)",
        )

        sender = email.get(
            "from",
            "(Unknown sender)",
        )

        status = email.get(
            "status",
            "OK",
        )

        # Show the email ID so specific test cases
        # such as email_434 can be found easily.
        label = f"{email_id} — {subject}"

        if st.button(
            label,
            key=f"email_{email_id}",
            use_container_width=True,
        ):
            st.session_state.selected_email_id = email_id
            st.rerun()

        st.caption(
            f"From: {sender}  |  {status_badge(status)}"
        )


def render_report(email):
    """Display the already-processed verification report."""

    if not email:
        st.info("Select an email from the inbox.")
        return

    email_id = email.get(
        "email_id",
        "",
    )

    st.subheader("📄 Verification Report")

    st.markdown(
        f"**Email ID:** `{email_id}`"
    )

    st.markdown(
        f"**Subject:** {email.get('subject', '—')}"
    )

    st.markdown(
        f"**From:** {email.get('from', '—')}"
    )

    st.divider()

    # Load the already-generated verification result.
    report = fetch_report(email_id)

    if not report:
        st.warning(
            "No verification report available for this email."
        )
        return

    status = report.get(
        "status",
        "UNKNOWN",
    )

    category = report.get(
        "category",
        "UNKNOWN",
    )

    reason = report.get(
        "review_reason"
    )

    defect_fields = report.get(
        "defect_fields",
        [],
    )

    # Main status.
    st.markdown(
        f"### Status: {status_badge(status)}"
    )

    # Summary cards.
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Category",
            format_category(category),
        )

    with col2:
        st.metric(
            "Status",
            format_status(status),
        )

    with col3:
        st.metric(
            "Defects",
            len(defect_fields),
        )

    # Human review reason.
    if reason:
        st.warning(
            f"Review reason: "
            f"{format_review_reason(reason)}"
        )

    # Side-by-side SI / BL comparison.
    _render_comparison_table(report)

    # Defect list.
    if defect_fields:
        st.markdown("### ⚠️ Issues Detected")

        for field in defect_fields:
            label = FIELD_LABELS.get(
                field,
                field.replace(
                    "_",
                    " ",
                ).title(),
            )

            st.write(
                f"• **{label}**"
            )


def _render_comparison_table(report):
    """Display SI and BL values side by side."""

    st.markdown("### Field Comparison")

    comparison = get_comparison(report)

    if not comparison:
        st.info(
            "Detailed field comparison is not "
            "available in this saved report."
        )
        return

    defect_fields = set(
        report.get(
            "defect_fields",
            [],
        )
    )

    rows = []

    for field_key, values in comparison.items():
        si_value, bl_value = values

        if field_key in defect_fields:
            result = "❌ MISMATCH"
        else:
            result = "✅ MATCH"

        rows.append(
            {
                "FIELD": FIELD_LABELS.get(
                    field_key,
                    field_key.replace(
                        "_",
                        " ",
                    ).title(),
                ),
                "SI VALUE": si_value,
                "BL VALUE": bl_value,
                "RESULT": result,
            }
        )

    st.table(rows)