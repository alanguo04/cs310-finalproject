import base64
import json

import requests
import streamlit as st


BASE_URL = "https://urv3reouhh.execute-api.us-east-2.amazonaws.com/prod"

def parse_response(response):
    try:
        payload = response.json()
    except Exception:
        return response.text

    if isinstance(payload, dict) and "body" in payload:
        try:
            return json.loads(payload["body"])
        except Exception:
            return payload

    return payload


def show_response(response):
    st.write("Status code:", response.status_code)
    parsed = parse_response(response)
    if isinstance(parsed, (dict, list)):
        st.json(parsed)
    else:
        st.text(str(parsed))
    return parsed


st.title("Final Project API Tester")
st.caption(f"Base URL: {BASE_URL}")

st.subheader("POST /segmentdata")
uploaded_file = st.file_uploader("Choose a GPX file", type=["gpx"])

if st.button("Upload GPX to /segmentdata"):
    if uploaded_file is None:
        st.warning("Please choose a GPX file first.")
    else:
        payload = {
            "filename": uploaded_file.name,
            "file": base64.b64encode(uploaded_file.read()).decode("utf-8"),
        }
        with st.spinner("Calling POST /segmentdata ..."):
            response = requests.post(f"{BASE_URL}/segmentdata", json=payload, timeout=300)
        parsed = show_response(response)
        if isinstance(parsed, dict) and parsed.get("run_id") is not None:
            st.success(f"Created run_id: {parsed['run_id']}")

st.divider()
st.subheader("GET /segmentdata/{runid}")
runid_segment_get = st.text_input("Run ID for segmentdata GET", key="runid_segment_get")
if st.button("Fetch Segment Data"):
    if not runid_segment_get.strip():
        st.warning("Enter a runid first.")
    else:
        with st.spinner("Calling GET /segmentdata/{runid} ..."):
            response = requests.get(f"{BASE_URL}/segmentdata/{runid_segment_get.strip()}", timeout=120)
        show_response(response)

st.divider()
st.subheader("PUT /pace (or /pace/{runid})")
runid_pace = st.text_input("Run ID for pace", key="runid_pace")
if st.button("Compute Pace"):
    if not runid_pace.strip():
        st.warning("Enter a runid first.")
    else:
        rid = runid_pace.strip()
        with st.spinner("Calling PUT /pace/{runid} ..."):
            response = requests.put(f"{BASE_URL}/pace/{rid}", timeout=180)

        # Current Lambda implementation expects body.run_id on PUT /pace.
        if response.status_code >= 400:
            with st.spinner("Retrying with PUT /pace and JSON body ..."):
                response = requests.put(f"{BASE_URL}/pace/{rid}", timeout=180)

        show_response(response)

st.divider()
st.subheader("PUT /heatmap/{runid}")
runid_heatmap_put = st.text_input("Run ID for heatmap generation", key="runid_heatmap_put")
if st.button("Generate Heatmap"):
    if not runid_heatmap_put.strip():
        st.warning("Enter a runid first.")
    else:
        with st.spinner("Calling PUT /heatmap/{runid} ..."):
            response = requests.put(f"{BASE_URL}/heatmap/{runid_heatmap_put.strip()}", timeout=180)
        parsed = show_response(response)
        if isinstance(parsed, dict) and parsed.get("visualization_url"):
            st.link_button("Open Visualization", parsed["visualization_url"])

st.divider()
st.subheader("GET /heatmap/{runid}")
runid_heatmap_get = st.text_input("Run ID for heatmap retrieval", key="runid_heatmap_get")
if st.button("Get Heatmap URL"):
    if not runid_heatmap_get.strip():
        st.warning("Enter a runid first.")
    else:
        with st.spinner("Calling GET /heatmap/{runid} ..."):
            response = requests.get(f"{BASE_URL}/heatmap/{runid_heatmap_get.strip()}", timeout=120)
        parsed = show_response(response)
        if isinstance(parsed, dict) and parsed.get("visualization_url"):
            st.link_button("Open Visualization", parsed["visualization_url"])
