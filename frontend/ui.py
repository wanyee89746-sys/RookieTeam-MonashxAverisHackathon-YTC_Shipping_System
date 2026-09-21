import time

import pandas as pd
import streamlit as st

from data import (
    fetch_evidence, fetch_raw, fetch_report, get_comparison,
    post_resolve, post_review,
)


CUSTOM_CSS = """
"""

BEFORE = "Raw inbox (before)"
AFTER = "Pipeline results (after)"

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


def is_done(item):
    if display_status(item) in ("OK", "CLASSIFIED_ONLY"):
        return True
    return bool(item.get("resolved"))


def workflow_label(item):
    if display_status(item) in ("OK", "CLASSIFIED_ONLY"):
        return "✔ No action needed"
    if item.get("resolved"):
        return "✔ Done"
    return "🔔 Action required"


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


def _s(value):
    return "" if value is None else str(value)


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
    cols[4].metric(
        "Action required",
        sum(1 for e in emails if not is_done(e)),
    )


# ---------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------

SORT_OPTIONS = ["Email ID", "Subject", "Status"]


def render_filters(emails):
    """Full-width filter bar. Returns (filtered_emails, raw_mode)."""

    if "view_mode" not in st.session_state:
        st.session_state.view_mode = AFTER

    # Apply the switch BEFORE the radio is created.
    if st.session_state.pop("switch_to_after", False):
        st.session_state.view_mode = AFTER

    top_a, top_b = st.columns([2, 1])

    with top_a:
        mode = st.radio(
            "View",
            [BEFORE, AFTER],
            horizontal=True,
            key="view_mode",
        )

    raw = mode == BEFORE

    with top_b:
        if raw:
            if st.button(
                "▶ Run pipeline",
                type="primary",
                use_container_width=True,
            ):
                bar = st.progress(0, text="Starting...")
                for pct, msg in [
                    (25, "Classifying emails..."),
                    (55, "Extracting SI and BL fields..."),
                    (80, "Comparing 7 fields..."),
                    (100, "Building reports..."),
                ]:
                    time.sleep(0.5)
                    bar.progress(pct, text=msg)

                st.session_state.switch_to_after = True
                st.rerun()

            st.caption("Replays saved pipeline output (precomputed).")

    status = category = flow = "All"

    if raw:
        c_search, c_sort = st.columns([3, 1])

        search = c_search.text_input(
            "Search",
            placeholder="Search email ID, subject, or sender...",
        )

        sort_by = c_sort.selectbox("Sort by", SORT_OPTIONS)

    else:
        categories = sorted(
            {e.get("category") for e in emails if e.get("category")}
        )

        c_search, c_status, c_cat, c_flow, c_sort = st.columns(
            [2.2, 1, 1, 1, 1]
        )

        search = c_search.text_input(
            "Search",
            placeholder="Search email ID, subject, or sender...",
        )

        status = c_status.selectbox(
            "Status",
            STATUS_OPTIONS,
            format_func=lambda s: (
                "All" if s == "All" else status_badge(s)
            ),
        )

        category = c_cat.selectbox(
            "Category",
            ["All"] + categories,
            format_func=lambda c: (
                "All"
                if c == "All"
                else format_category(c)
            ),
        )

        flow = c_flow.selectbox(
            "Workflow",
            ["All", "Action required", "Done"],
        )

        sort_by = c_sort.selectbox("Sort by", SORT_OPTIONS)

    filtered = emails

    if search:
        q = search.lower()

        filtered = [
            e
            for e in filtered
            if q in str(e.get("email_id", "")).lower()
            or q in str(e.get("subject", "")).lower()
            or q in str(e.get("from", "")).lower()
        ]

    if status != "All":
        filtered = [
            e for e in filtered
            if display_status(e) == status
        ]

    if category != "All":
        filtered = [
            e for e in filtered
            if e.get("category") == category
        ]

    if flow == "Action required":
        filtered = [
            e for e in filtered
            if not is_done(e)
        ]

    elif flow == "Done":
        filtered = [
            e for e in filtered
            if is_done(e)
        ]

    if sort_by == "Email ID":
        filtered = sorted(
            filtered,
            key=lambda e: e.get("email_id", ""),
        )

    elif sort_by == "Subject":
        filtered = sorted(
            filtered,
            key=lambda e: str(e.get("subject", "")).lower(),
        )

    elif sort_by == "Status":
        filtered = sorted(
            filtered,
            key=display_status,
        )

    return filtered, raw


def render_inbox_list(filtered, total, raw):
    """Scrollable email list."""

    st.subheader("📥 Email Inbox")
    st.caption(f"Showing {len(filtered)} of {total} emails")

    if not filtered:
        st.info("No emails match your search/filter.")
        return

    selected_id = st.session_state.get("selected_email_id")

    with st.container(height=700):
        for email in filtered:
            email_id = email.get("email_id", "")
            sender = email.get("from", "(Unknown sender)")

            if st.button(
                f"{email_id} — {email.get('subject', '(No subject)')}",
                key=f"email_{email_id}",
                use_container_width=True,
                type=(
                    "primary"
                    if email_id == selected_id
                    else "secondary"
                ),
            ):
                st.session_state.selected_email_id = email_id
                st.rerun()

            if raw:
                n = len(email.get("attachments") or [])

                st.caption(
                    f"From: {sender}  |  📎 {n} attachment(s)  |  "
                    "⏳ Not processed"
                )

            else:
                cat = email.get("category")
                cat_text = (
                    f"{format_category(cat)}  |  "
                    if cat
                    else ""
                )

                st.caption(
                    f"From: {sender}  |  {cat_text}"
                    f"{status_badge(display_status(email))}  |  "
                    f"{workflow_label(email)}"
                )


# ---------------------------------------------------------------
# Raw email (before pipeline)
# ---------------------------------------------------------------

def _render_raw(email_id):
    st.markdown("### Email as received")

    st.info(
        "Not processed yet. Click **▶ Run pipeline** in the inbox "
        "to see the result."
    )

    record = fetch_raw(email_id)

    if not record:
        st.warning("Could not load the raw email.")
        return

    atts = record.get("attachments") or []

    if not atts:
        st.warning(
            "No attachments. A comparison request without SI/BL "
            "can't be checked."
        )

    else:
        st.markdown("**Attachments:**")

        for a in atts:
            st.write(f"📎 {a}")

        ev = fetch_evidence(email_id)

        if ev and (ev.get("si_text") or ev.get("bl_text")):
            c1, c2 = st.columns(2)

            for col, label, path, text in [
                (c1, "SI", ev.get("si_path"), ev.get("si_text")),
                (c2, "BL", ev.get("bl_path"), ev.get("bl_text")),
            ]:
                with col:
                    st.markdown(f"**{label} preview**")
                    st.caption(
                        path or f"no {label} attachment"
                    )

                    st.text_area(
                        f"{label} text",
                        text or "No text available",
                        height=300,
                        disabled=True,
                        key=f"{label}_prev_{email_id}",
                        label_visibility="collapsed",
                    )

    with st.expander("Raw email record"):
        st.json(record)


# ---------------------------------------------------------------
# AI Recovery
# ---------------------------------------------------------------

def _render_ai_recovery(report):
    """Show Vision LLM recovery information for unreadable documents."""

    si_vision = (
        report.get("si_vision_used") is True
        and report.get("si_vision_success") is True
    )

    bl_vision = (
        report.get("bl_vision_used") is True
        and report.get("bl_vision_success") is True
    )

    if not (si_vision or bl_vision):
        return

    st.markdown("### 🤖 AI Recovery")

    st.info(
        "Standard document extraction could not read the document. "
        "Vision LLM was used to recover the document information."
    )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Shipping Instruction (SI)**")

        if si_vision:
            st.success("✅ Vision LLM recovery successful")
            st.caption(
                "Extraction method: "
                f"`{report.get('si_extraction_method', 'vision_llm')}`"
            )
        else:
            st.warning("Vision LLM recovery not successful")

    with col2:
        st.markdown("**Bill of Lading (BL)**")

        if bl_vision:
            st.success("✅ Vision LLM recovery successful")
            st.caption(
                "Extraction method: "
                f"`{report.get('bl_extraction_method', 'vision_llm')}`"
            )
        else:
            st.warning("Vision LLM recovery not successful")

    st.caption(
        "Note: The official verification status remains unchanged. "
        "For unreadable documents, the case still requires human review."
    )


# ---------------------------------------------------------------
# Human review
# ---------------------------------------------------------------

def _render_review(email_id, report, comparison):
    st.markdown("### 🧑‍⚖️ Human review")

    if report.get("reviewed") and report.get("original_status"):
        st.caption(
            "Reviewer corrected values. Original pipeline result: "
            f"{status_badge(report['original_status'])}"
        )

    with st.expander("Source evidence (extracted text)"):
        ev = fetch_evidence(email_id)

        c1, c2 = st.columns(2)

        c1.caption(
            f"SI: {ev.get('si_path') or 'no attachment'}"
        )
        c1.text(
            ev.get("si_text") or "No text available"
        )

        c2.caption(
            f"BL: {ev.get('bl_path') or 'no attachment'}"
        )
        c2.text(
            ev.get("bl_text") or "No text available"
        )

    keys = list(FIELD_LABELS)

    base = pd.DataFrame(
        {
            "Field": [_label(f) for f in keys],
            "SI": [
                _s(comparison.get(f, (None, None))[0])
                for f in keys
            ],
            "BL": [
                _s(comparison.get(f, (None, None))[1])
                for f in keys
            ],
        }
    )

    st.caption(
        "Edit any SI or BL value, then save to recompute the result."
    )

    edited = st.data_editor(
        base,
        hide_index=True,
        disabled=["Field"],
        use_container_width=True,
        key=f"edit_{email_id}",
    )

    note = st.text_input(
        "Reviewer note",
        value=report.get("note") or "",
        key=f"note_{email_id}",
    )

    c1, c2 = st.columns(2)

    if c1.button(
        "Save corrections & recompute",
        key=f"save_{email_id}",
    ):
        corrections = {}

        for i, f in enumerate(keys):
            change = {}

            if edited.at[i, "SI"] != base.at[i, "SI"]:
                change["si"] = edited.at[i, "SI"]

            if edited.at[i, "BL"] != base.at[i, "BL"]:
                change["bl"] = edited.at[i, "BL"]

            if change:
                corrections[f] = change

        if corrections:
            post_review(
                email_id,
                corrections,
                note,
            )
            st.rerun()

        else:
            st.info("No changes to save.")

    done = bool(report.get("resolved"))

    if c2.button(
        "↩ Reopen" if done else "✔ Mark as done",
        key=f"done_{email_id}",
        type="secondary" if done else "primary",
    ):
        post_resolve(
            email_id,
            not done,
            note,
        )
        st.rerun()


# ---------------------------------------------------------------
# Report
# ---------------------------------------------------------------

def render_report(email):
    """Display the verification report (or the raw email in 'before' view)."""

    if not email:
        st.info("Select an email from the inbox.")
        return

    email_id = email.get("email_id", "")

    # Before-pipeline view: show the email as received.
    if st.session_state.get("view_mode") == BEFORE:
        st.subheader("📄 Email")
        st.markdown(f"**Email ID:** `{email_id}`")
        st.markdown(
            f"**Subject:** {email.get('subject', '—')}"
        )
        st.markdown(
            f"**From:** {email.get('from', '—')}"
        )
        st.divider()

        _render_raw(email_id)
        return

    st.subheader("📄 Verification Report")
    st.markdown(f"**Email ID:** `{email_id}`")
    st.markdown(
        f"**Subject:** {email.get('subject', '—')}"
    )
    st.markdown(
        f"**From:** {email.get('from', '—')}"
    )

    st.divider()

    report = fetch_report(email_id)

    if not report:
        st.warning(
            "No verification report available for this email."
        )
        return

    status = display_status(report)
    category = report.get("category")
    reason = report.get("review_reason")
    defect_fields = report.get("defect_fields") or []
    unverified = _unverified_fields(report)
    comparison = get_comparison(report)

    st.markdown(
        f"### Status: {status_badge(status)}"
    )
    st.caption(workflow_label(report))

    # Non-comparison emails stop here.
    if status == "CLASSIFIED_ONLY":
        st.info(
            f"Classified as **{format_category(category)}**. "
            "Only BL comparison requests go through the document check."
        )
        return

    if status == "MISMATCH":
        st.error(
            f"{len(defect_fields)} mismatch(es) found. "
            "See details below."
        )

    elif status == "NEEDS_REVIEW":
        st.warning(
            f"Human review required: "
            f"{format_review_reason(reason)}"
        )

    elif status == "OK":
        if unverified:
            st.warning(
                "No mismatch detected in the checked fields, "
                "but these could not be verified: "
                + ", ".join(
                    _label(f)
                    for f in unverified
                )
            )
        else:
            st.success(
                "No mismatch detected. All 7 fields match."
            )

    # -----------------------------------------------------------
    # AI Recovery
    # -----------------------------------------------------------
    _render_ai_recovery(report)

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Category",
        format_category(category),
    )

    col2.metric(
        "Mismatches",
        len(defect_fields),
    )

    col3.metric(
        "Unverified fields",
        len(unverified),
    )

    _render_issues(
        defect_fields,
        comparison,
    )

    _render_comparison_table(
        report,
        comparison,
    )

    if status in ("MISMATCH", "NEEDS_REVIEW") or report.get("reviewed"):
        st.divider()

        _render_review(
            email_id,
            report,
            comparison,
        )


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
            st.write(
                f"• **{_label(field)}**"
            )


def _highlight_row(row):
    colors = {
        "❌ MISMATCH": (
            "background-color: rgba(220, 53, 69, 0.18)"
        ),
        "⚠️ UNVERIFIED": (
            "background-color: rgba(255, 165, 0, 0.18)"
        ),
    }

    return [
        colors.get(row["RESULT"], "")
    ] * len(row)


def _render_comparison_table(report, comparison):
    """Always show all 7 fields side by side for BL comparison emails."""

    st.markdown("### Field Comparison")

    defect_fields = set(
        report.get("defect_fields") or []
    )

    field_results = report.get("field_results") or {}

    has_values = bool(comparison)

    rows = []

    for field in FIELD_LABELS:
        si_value, bl_value = comparison.get(
            field,
            (None, None),
        )

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
                "SI VALUE": (
                    _fmt(si_value)
                    if has_values
                    else "—"
                ),
                "BL VALUE": (
                    _fmt(bl_value)
                    if has_values
                    else "—"
                ),
                "RESULT": result,
            }
        )

    st.dataframe(
        pd.DataFrame(rows).style.apply(
            _highlight_row,
            axis=1,
        ),
        hide_index=True,
        use_container_width=True,
    )

    if not has_values:
        st.caption(
            "SI/BL values were not saved for this email. "
            "Re-run the pipeline for it to see them."
        )
