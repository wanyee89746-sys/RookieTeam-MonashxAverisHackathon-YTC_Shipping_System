"""
Data layer for the Shipping Document Verification frontend.

The frontend reads already-processed verification results
from the FastAPI backend. It does not run the verification
pipeline itself.
"""

import requests
import streamlit as st


API_BASE_URL = "http://127.0.0.1:8000"


FIELD_LABELS = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify Party",
    "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge",
    "container_count": "Container Count",
    "gross_weight_kg": "Gross Weight (kg)",
}


@st.cache_data(ttl=30)
def fetch_emails():
    """Get the processed email list from the FastAPI backend."""

    try:
        response = requests.get(
            f"{API_BASE_URL}/emails",
            timeout=10,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException as e:
        st.error(
            f"Could not load emails from the API: {e}"
        )

        return []


@st.cache_data(ttl=30)
def fetch_report(email_id):
    """Get the processed verification report for one email."""

    try:
        response = requests.get(
            f"{API_BASE_URL}/emails/{email_id}/report",
            timeout=10,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        return response.json()

    except requests.RequestException as e:
        st.error(
            f"Could not load report for {email_id}: {e}"
        )

        return None


def get_comparison(report):
    """
    Convert the backend field comparison into:

        {
            "field_name": (si_value, bl_value)
        }

    The current backend stores detailed values in:

        report["field_values"]

    Example:

        "shipper": {
            "si": "...",
            "bl": "..."
        }
    """

    if not report:
        return {}

    raw_fields = report.get("field_values") or {}

    comparison = {}

    for field_key in FIELD_LABELS:
        value = raw_fields.get(field_key)

        if value is None:
            continue

        if isinstance(value, dict):
            comparison[field_key] = (
                value.get("si", "—"),
                value.get("bl", "—"),
            )

        elif (
            isinstance(value, (list, tuple))
            and len(value) >= 2
        ):
            comparison[field_key] = (
                value[0],
                value[1],
            )

    return comparison
