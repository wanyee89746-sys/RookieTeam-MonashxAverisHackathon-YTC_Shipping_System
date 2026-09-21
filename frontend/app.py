import streamlit as st
from textwrap import dedent
from mock_data import emails


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Shipping Document Verification",
    page_icon="🚢",
    layout="wide"
)


# =========================================================
# MOCK DATA
# =========================================================

# 7 fields used by the document comparison system
FIELD_LABELS = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify Party",
    "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge",
    "container_count": "Container Count",
    "gross_weight_kg": "Gross Weight (kg)",
}


# Mock comparison data for UI testing
comparison_data = {

    "email_001": {
        "shipper": ("APRIL FAR EAST (M) SDN BHD",
                    "APRIL FAR EAST (M) SDN BHD"),

        "consignee": ("MOORIM SP CO., LTD",
                      "MOORIM SP CO., LTD"),

        "notify_party": ("UAB NOVAKOPA",
                         "UAB NOVAKOPA"),

        "port_of_loading": ("PORT KLANG (WESTPORT), MALAYSIA",
                            "PORT KLANG (WESTPORT), MALAYSIA"),

        "port_of_discharge": ("CALLAO, PERU",
                              "CALLAO, PERU"),

        "container_count": ("1",
                            "1"),

        "gross_weight_kg": ("21577",
                            "21577"),
    },


    "email_002": {
        "shipper": ("APRIL FAR EAST (M) SDN BHD",
                    "APRIL FAR EAST (M) SDN BHD"),

        "consignee": ("MOORIM SP CO., LTD",
                      "MOORIM SP CO., LTD"),

        "notify_party": ("UAB NOVAKOPA",
                         "UAB NOVAKOPA"),

        "port_of_loading": ("PORT KLANG (WESTPORT), MALAYSIA",
                            "PORT KLANG (WESTPORT), MALAYSIA"),

        "port_of_discharge": ("CALLAO, PERU",
                              "CALLAO, PERU"),

        "container_count": ("1",
                            "1"),

        "gross_weight_kg": ("21577",
                            "22000"),
    },


    "email_003": {
        "shipper": ("APRIL FAR EAST (M) SDN BHD",
                    "APRIL FAR EAST (M) SDN BHD"),

        "consignee": ("MOORIM SP CO., LTD",
                      "MOORIM SP CO., LTD"),

        "notify_party": ("UAB NOVAKOPA",
                         "UAB NOVAKOPA"),

        "port_of_loading": ("PORT KLANG",
                            "PORT KLANG"),

        "port_of_discharge": ("CALLAO",
                              "CALLAO"),

        "container_count": ("1",
                            "1"),

        "gross_weight_kg": ("21577",
                            "21577"),
    },
}


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def format_category(category):

    category_names = {
        "GENERAL": "General",
        "BL_COMPARISON": "Document Comparison",
        "DOCUMENT_COMPARISON": "Document Comparison",
        "NEW_SI_REQUEST": "New SI Request",
        "INVOICE_QUERY": "Invoice Query",
        "SPAM": "Spam",
    }

    return category_names.get(
        category,
        category.replace("_", " ").title()
    )


def format_status(status):

    if status == "OK":
        return "✓ OK"

    elif status == "MISMATCH":
        return "⚠ Mismatch"

    elif status in ("NEEDS_REVIEW", "ESCALATE"):
        return "⚠ Needs Review"

    else:
        return status.title()


def status_class(status):

    if status == "OK":
        return "status-ok"

    elif status == "MISMATCH":
        return "status-mismatch"

    else:
        return "status-review"


def get_comparison(email_id):

    return comparison_data.get(email_id, {})


# =========================================================
# SESSION STATE
# =========================================================

if "selected_email_id" not in st.session_state:

    st.session_state.selected_email_id = None


# =========================================================
# CUSTOM CSS
# =========================================================

st.markdown(
    dedent("""
    <style>

    /* =====================================================
       GENERAL
       ===================================================== */

    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }


    /* =====================================================
       INBOX EMAIL BUTTONS
       ===================================================== */

    div.stButton > button {

        width: 100% !important;

        min-height: 82px !important;

        padding: 10px 14px !important;

        text-align: left !important;

        background-color: white !important;

        color: #1f2937 !important;

        border: none !important;

        border-bottom: 1px solid #e5e7eb !important;

        border-radius: 0 !important;

        box-shadow: none !important;

        display: flex !important;

        justify-content: flex-start !important;

        align-items: center !important;
    }


    div.stButton > button:hover {

        background-color: #f5f6f7 !important;

        color: #1f2937 !important;
    }


    div.stButton > button > div {

        width: 100% !important;

        text-align: left !important;

        justify-content: flex-start !important;
    }


    div.stButton > button p {

        width: 100% !important;

        text-align: left !important;

        white-space: pre-line !important;

        margin: 0 !important;

        line-height: 1.5 !important;
    }


    /* =====================================================
       EMAIL ROW
       ===================================================== */

    .email-subject {

        font-size: 15px;

        font-weight: 600;

        line-height: 1.4;

        margin-bottom: 4px;
    }


    .email-meta {

        font-size: 12px;

        color: #777777;

        line-height: 1.4;
    }


    /* =====================================================
       STATUS BADGES
       ===================================================== */

    .badge {

        display: inline-block;

        padding: 4px 9px;

        border-radius: 999px;

        font-size: 12px;

        font-weight: 600;

        margin-left: 5px;
    }


    .badge-ok {

        background-color: #dcfce7;

        color: #166534;
    }


    .badge-mismatch {

        background-color: #fef3c7;

        color: #92400e;
    }


    .badge-review {

        background-color: #fee2e2;

        color: #991b1b;
    }


    /* =====================================================
       REPORT HEADER
       ===================================================== */

    .report-title {

        font-size: 28px;

        font-weight: 700;

        line-height: 1.25;

        margin-bottom: 5px;
    }


    .report-sender {

        color: #4a90e2;

        font-size: 14px;

        margin-bottom: 20px;
    }


    /* =====================================================
       REPORT INFO
       ===================================================== */

    .info-card {

        background-color: #f8fafc;

        border: 1px solid #e5e7eb;

        border-radius: 10px;

        padding: 16px;

        margin-top: 12px;

        margin-bottom: 20px;
    }


    .info-label {

        font-size: 12px;

        color: #6b7280;

        margin-bottom: 4px;
    }


    .info-value {

        font-size: 15px;

        font-weight: 600;

        color: #111827;
    }


    /* =====================================================
       COMPARISON TABLE
       ===================================================== */

    .comparison-table {

        width: 100%;

        border-collapse: collapse;

        margin-top: 12px;

        margin-bottom: 20px;

        font-size: 13px;
    }


    .comparison-table th {

        background-color: #f8fafc;

        border-bottom: 2px solid #e5e7eb;

        padding: 11px 10px;

        text-align: left;

        font-weight: 600;

        color: #374151;
    }


    .comparison-table td {

        border-bottom: 1px solid #e5e7eb;

        padding: 11px 10px;

        vertical-align: top;

        color: #374151;
    }


    .comparison-table tr:hover {

        background-color: #fafafa;
    }


    .field-name {

        font-weight: 600;

        color: #111827;
    }


    .match {

        color: #16a34a;

        font-weight: 700;
    }


    .mismatch {

        color: #dc2626;

        font-weight: 700;
    }


    /* =====================================================
       REVIEW BOX
       ===================================================== */

    .review-box {

        background-color: #fff7ed;

        border: 1px solid #fed7aa;

        border-left: 4px solid #f97316;

        border-radius: 8px;

        padding: 15px 18px;

        margin-top: 15px;

        margin-bottom: 20px;
    }


    .review-title {

        font-size: 15px;

        font-weight: 700;

        color: #9a3412;

        margin-bottom: 5px;
    }


    .review-text {

        font-size: 14px;

        color: #7c2d12;
    }


    /* =====================================================
       EMPTY REPORT
       ===================================================== */

    .empty-state {

        text-align: center;

        padding-top: 100px;

        color: #6b7280;
    }


    .empty-icon {

        font-size: 45px;

        margin-bottom: 15px;
    }


    .empty-title {

        font-size: 20px;

        font-weight: 600;

        color: #374151;

        margin-bottom: 5px;
    }

    </style>
    """),
    unsafe_allow_html=True
)


# =========================================================
# HEADER
# =========================================================

st.title("🚢 Shipping Document Verification")

st.caption(
    "Automated email and shipping document verification"
)

st.divider()


# =========================================================
# MAIN LAYOUT
# =========================================================

inbox_col, report_col = st.columns(
    [1.15, 2],
    gap="large"
)


# =========================================================
# INBOX
# =========================================================

with inbox_col:

    st.subheader("📥 Inbox")

    st.caption(
        f"{len(emails)} emails"
    )

    st.markdown(
        "<div style='height: 4px'></div>",
        unsafe_allow_html=True
    )


    for email in emails:

        email_id = email["email_id"]

        subject = email.get(
            "subject",
            "No subject"
        )

        sender = email.get(
            "from",
            "Unknown sender"
        )

        category = format_category(
            email.get(
                "category",
                "GENERAL"
            )
        )

        status = email.get(
            "status",
            "OK"
        )


        # -------------------------------------------------
        # Status badge
        # -------------------------------------------------

        if status == "OK":

            badge = "✓ OK"

            badge_class = "badge-ok"

        elif status == "MISMATCH":

            badge = "⚠ Mismatch"

            badge_class = "badge-mismatch"

        else:

            badge = "⚠ Needs Review"

            badge_class = "badge-review"


        # -------------------------------------------------
        # Button label
        #
        # Streamlit button supports newline.
        # -------------------------------------------------

        label = (
            f"{subject}\n"
            f"{sender} · {category} · {badge}"
        )


        # -------------------------------------------------
        # Click email
        # -------------------------------------------------

        if st.button(
            label,
            key=f"email_{email_id}",
            use_container_width=True
        ):

            st.session_state.selected_email_id = email_id

            st.rerun()


# =========================================================
# FIND SELECTED EMAIL
# =========================================================

selected_email = None


for email in emails:

    if (
        email["email_id"]
        == st.session_state.selected_email_id
    ):

        selected_email = email

        break


# =========================================================
# REPORT
# =========================================================

with report_col:

    st.subheader("📄 Verification Report")


    # =====================================================
    # NOTHING SELECTED
    # =====================================================

    if selected_email is None:

        st.html(
            dedent(f"""
            <div class="empty-state">

                <div class="empty-icon">
                    📄
                </div>

                <div class="empty-title">
                    No email selected
                </div>

                <div>
                    Select an email from the inbox
                    to view its verification report.
                </div>

            </div>
            """).strip()
        )


    # =====================================================
    # EMAIL SELECTED
    # =====================================================

    else:

        email_id = selected_email["email_id"]

        subject = selected_email.get(
            "subject",
            "No subject"
        )

        sender = selected_email.get(
            "from",
            "Unknown sender"
        )

        category = selected_email.get(
            "category",
            "GENERAL"
        )

        status = selected_email.get(
            "status",
            "OK"
        )

        review_reason = selected_email.get(
            "review_reason"
        )

        defect_fields = selected_email.get(
            "defect_fields",
            []
        )

        has_defect = selected_email.get(
            "has_defect",
            False
        )


        # =================================================
        # TITLE
        # =================================================

        st.html(
            dedent(f"""
            <div class="report-title">
                {subject}
            </div>

            <div class="report-sender">
                {sender}
            </div>
            """).strip()
        )


        # =================================================
        # STATUS / CATEGORY CARDS
        # =================================================

        info_col1, info_col2 = st.columns(2)


        with info_col1:

            st.html(
                dedent(f"""
                <div class="info-card">

                    <div class="info-label">
                        Category
                    </div>

                    <div class="info-value">
                        {format_category(category)}
                    </div>

                </div>
                """).strip()
            )


        with info_col2:

            st.html(
                dedent(f"""
                <div class="info-card">

                    <div class="info-label">
                        Status
                    </div>

                    <div class="info-value">
                        {format_status(status)}
                    </div>

                </div>
                """).strip()
            )


        # =================================================
        # NEEDS REVIEW
        # =================================================

        if status in (
            "NEEDS_REVIEW",
            "ESCALATE"
        ):

            reason_text = (
                review_reason
                or "The system could not safely complete the verification."
            )


            reason_names = {

                "missing_attachment":
                    "Missing attachment",

                "unreadable":
                    "Attachment is unreadable",

                "wrong_doc_type":
                    "Wrong document type",

                "extraction_failed":
                    "Document extraction failed",

                "missing_value":
                    "Required value is missing",
            }


            display_reason = reason_names.get(
                reason_text,
                reason_text.replace(
                    "_",
                    " "
                ).title()
            )


            st.html(
                dedent(f"""
                <div class="review-box">

                    <div class="review-title">
                        ⚠ Human Review Required
                    </div>

                    <div class="review-text">
                        <strong>Reason:</strong>
                        {display_reason}
                    </div>

                </div>
                """).strip()
            )


        # =================================================
        # MISMATCH SUMMARY
        # =================================================

        elif status == "MISMATCH":

            st.warning(
                f"⚠️ Mismatch detected in "
                f"{len(defect_fields)} field(s)."
            )


        # =================================================
        # OK SUMMARY
        # =================================================

        elif status == "OK":

            st.success(
                "✓ All required fields matched successfully."
            )


        # =================================================
        # FIELD COMPARISON
        # =================================================

        st.markdown(
            "### Field Comparison"
        )


        comparison = get_comparison(
            email_id
        )


        if comparison:

            rows = ""


            for field_key, field_label in FIELD_LABELS.items():

                values = comparison.get(
                    field_key,
                    ("—", "—")
                )


                si_value = values[0]

                bl_value = values[1]


                is_match = (
                    str(si_value).strip().upper()
                    ==
                    str(bl_value).strip().upper()
                )


                # If backend says this field is defective,
                # treat it as mismatch in UI.

                if field_key in defect_fields:

                    is_match = False


                if is_match:

                    result_html = (
                        "<span class='match'>✓ Match</span>"
                    )

                else:

                    result_html = (
                        "<span class='mismatch'>"
                        "✗ Mismatch"
                        "</span>"
                    )


                rows += dedent(f"""
                    <tr>

                        <td class="field-name">
                            {field_label}
                        </td>

                        <td>
                            {si_value}
                        </td>

                        <td>
                            {bl_value}
                        </td>

                        <td>
                            {result_html}
                        </td>

                    </tr>
                """)


            st.html(
                dedent(f"""
                <table class="comparison-table">

                    <thead>

                        <tr>

                            <th>
                                Field
                            </th>

                            <th>
                                SI
                            </th>

                            <th>
                                BL
                            </th>

                            <th>
                                Result
                            </th>

                        </tr>

                    </thead>

                    <tbody>

                        {rows}

                    </tbody>

                </table>
                """).strip()
            )


        else:

            # Non-document-comparison emails

            st.info(
                "Field comparison is only available "
                "for document comparison cases."
            )


        # =================================================
        # DEFECT FIELDS
        # =================================================

        if defect_fields:

            st.markdown(
                "### Detected Issues"
            )


            for field in defect_fields:

                display_name = FIELD_LABELS.get(
                    field,
                    field.replace(
                        "_",
                        " "
                    ).title()
                )


                st.markdown(
                    f"- **{display_name}**"
                )