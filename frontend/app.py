import streamlit as st

from data import fetch_emails
from ui import (
    CUSTOM_CSS, render_filters, render_inbox_list,
    render_report, render_summary,
)

st.set_page_config(
    page_title="Shipping Document Verification",
    page_icon="🚢",
    layout="wide"
)


if "selected_email_id" not in st.session_state:
    st.session_state.selected_email_id = None

if "selected_report" not in st.session_state:
    st.session_state.selected_report = None


st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title("🚢 Shipping Document Verification")
st.caption("Automated email and shipping document verification")
st.divider()


emails = fetch_emails()

render_summary(emails)
st.divider()

filtered, raw = render_filters(emails)

st.divider()

inbox_col, report_col = st.columns([1, 2], gap="large")

with inbox_col:
    render_inbox_list(filtered, len(emails), raw)


selected_email = next(
    (
        email
        for email in emails
        if email["email_id"]
        == st.session_state.selected_email_id
    ),
    None
)


with report_col:
    render_report(selected_email)