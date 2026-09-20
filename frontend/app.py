import streamlit as st
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
# HELPER FUNCTIONS
# =========================================================

def format_category(category):

    category_names = {
        "GENERAL": "General",
        "DOCUMENT_COMPARISON": "Document Comparison",
        "NEW_SI_REQUEST": "New SI Request",
        "INVOICE_QUERY": "Invoice Query",
        "SPAM": "Spam"
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

    elif status == "ESCALATE":
        return "⚠ Escalate"

    else:
        return status.title()


# =========================================================
# SELECTED EMAIL
# =========================================================

if "selected_email_id" not in st.session_state:
    st.session_state.selected_email_id = None


# =========================================================
# CUSTOM CSS
# =========================================================

st.markdown(
    """
    <style>

    /* ---------------------------------------------
       Inbox email row
    --------------------------------------------- */

    div.stButton > button {
    width: 100% !important;
    min-height: 70px !important;

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


/* Force the button content to the left */

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
}


div.stButton > button:hover {
    background-color: #f5f6f7 !important;
    color: #1f2937 !important;
}


    /* ---------------------------------------------
       Email text
    --------------------------------------------- */

    .email-subject {
        font-size: 15px;
        font-weight: 600;
        line-height: 1.4;
    }


    .email-meta {
        font-size: 13px;
        color: #777777;
        line-height: 1.4;
        margin-top: 3px;
    }


    /* ---------------------------------------------
       Report
    --------------------------------------------- */

    .report-title {
        font-size: 28px;
        font-weight: 700;
        margin-bottom: 8px;
    }


    .report-sender {
        color: #4a90e2;
        margin-bottom: 20px;
    }

    </style>
    """,
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

    for email in emails:

        email_id = email["email_id"]

        subject = email["subject"]

        sender = email["from"]

        category = format_category(
            email["category"]
        )

        status = format_status(
            email["status"]
        )


        # ---------------------------------------------
        # Selected email
        # ---------------------------------------------

        is_selected = (
            email_id == st.session_state.selected_email_id
        )


        # ---------------------------------------------
        # Display text
        # ---------------------------------------------

        label = (
    f"{subject}\n"
    f"{sender} · {category} · {status}"
)


        # ---------------------------------------------
        # Click email
        # ---------------------------------------------

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

    if email["email_id"] == st.session_state.selected_email_id:

        selected_email = email

        break


# =========================================================
# REPORT
# =========================================================

with report_col:

    st.subheader("📄 Report")


    # ---------------------------------------------
    # Nothing selected
    # ---------------------------------------------

    if selected_email is None:

        st.info(
            "Select an email from the inbox to view its report."
        )


    # ---------------------------------------------
    # Email selected
    # ---------------------------------------------

    else:

        st.markdown(
            f"""
            <div class="report-title">
                {selected_email["subject"]}
            </div>

            <div class="report-sender">
                {selected_email["from"]}
            </div>
            """,
            unsafe_allow_html=True
        )


        st.write(
            f"**Category:** "
            f"{format_category(selected_email['category'])}"
        )


        st.write(
            f"**Status:** "
            f"{format_status(selected_email['status'])}"
        )


        # ---------------------------------------------
        # Review reason
        # ---------------------------------------------

        if selected_email.get("review_reason"):

            st.write(
                f"**Review reason:** "
                f"{selected_email['review_reason']}"
            )


        # ---------------------------------------------
        # Defect fields
        # ---------------------------------------------

        defect_fields = selected_email.get(
            "defect_fields",
            []
        )


        if defect_fields:

            st.write("**Defect fields:**")

            for field in defect_fields:

                st.write(f"- {field}")


        # ---------------------------------------------
        # Defect status
        # ---------------------------------------------

        if selected_email.get(
            "has_defect",
            False
        ):

            st.warning(
                "⚠️ A mismatch was detected."
            )

        else:

            st.success(
                "✓ No mismatch detected."
            )