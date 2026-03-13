import base64
import json

import pandas as pd
import requests
import streamlit as st


BASE_URL = "https://urv3reouhh.execute-api.us-east-2.amazonaws.com/prod"

st.set_page_config(
    page_title="Run Analytics Dashboard",
    page_icon=":runner:",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.3rem; max-width: 1200px;}
      .api-card {
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        padding: 14px 16px;
        background: #FFFFFF;
        margin-bottom: 12px;
      }
      .api-title {font-size: 1.05rem; font-weight: 700; margin-bottom: 0.2rem;}
      .api-subtitle {color: #4B5563; font-size: 0.92rem;}
      .status-ok {color: #15803d; font-weight: 700;}
      .status-bad {color: #b91c1c; font-weight: 700;}
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_response(response: requests.Response):
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


def show_response(response: requests.Response, title: str):
    status_class = "status-ok" if response.status_code < 400 else "status-bad"
    st.markdown(
        f"""
        <div class="api-card">
          <div class="api-title">{title}</div>
          <div class="api-subtitle">Status: <span class="{status_class}">{response.status_code}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    parsed = parse_response(response)
    if isinstance(parsed, (dict, list)):
        st.json(parsed)
    else:
        st.text(str(parsed))
    return parsed


def extract_segments(parsed):
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("segments", "data", "segmentdata", "items"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    return None


def render_segments_table(parsed):
    segments = extract_segments(parsed)
    if not segments:
        st.info("No segment rows found in this payload.")
        return

    df = pd.DataFrame(segments)
    st.markdown("### Segment Table")
    st.dataframe(df, use_container_width=True, height=420)

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", len(df))
    c2.metric("Columns", len(df.columns))
    if "pace" in df.columns:
        valid = pd.to_numeric(df["pace"], errors="coerce").dropna()
        c3.metric("Avg Pace", f"{valid.mean():.2f}" if not valid.empty else "N/A")
    else:
        c3.metric("Avg Pace", "N/A")


st.title("Run Analytics Dashboard")
st.caption(f"API Base URL: `{BASE_URL}`")

tab_upload, tab_segments, tab_pace, tab_heatmap = st.tabs(
    ["Upload Run", "Segment Data", "Pace", "Heatmap"]
)

with tab_upload:
    st.markdown(
        '<div class="api-card"><div class="api-title">POST /segmentdata</div><div class="api-subtitle">Upload GPX and create run + segment records.</div></div>',
        unsafe_allow_html=True,
    )
    uploaded_file = st.file_uploader("Choose a GPX file", type=["gpx"])
    if st.button("Upload GPX", use_container_width=True):
        if uploaded_file is None:
            st.warning("Please choose a GPX file first.")
        else:
            payload = {
                "filename": uploaded_file.name,
                "file": base64.b64encode(uploaded_file.read()).decode("utf-8"),
            }
            with st.spinner("Uploading to /segmentdata ..."):
                response = requests.post(f"{BASE_URL}/segmentdata", json=payload, timeout=300)
            parsed = show_response(response, "Upload Result")
            if isinstance(parsed, dict) and parsed.get("run_id") is not None:
                st.success(f"Created run_id: {parsed['run_id']}")

with tab_segments:
    st.markdown(
        '<div class="api-card"><div class="api-title">GET /segmentdata/{runid}</div><div class="api-subtitle">View enriched segments as an interactive table.</div></div>',
        unsafe_allow_html=True,
    )
    runid_segment_get = st.text_input("Run ID", key="runid_segment_get")
    if st.button("Fetch Segment Data", use_container_width=True):
        if not runid_segment_get.strip():
            st.warning("Enter a runid first.")
        else:
            with st.spinner("Calling GET /segmentdata/{runid} ..."):
                response = requests.get(f"{BASE_URL}/segmentdata/{runid_segment_get.strip()}", timeout=120)
            parsed = show_response(response, "Segment Data Response")
            render_segments_table(parsed)

with tab_pace:
    st.markdown(
        '<div class="api-card"><div class="api-title">PUT /pace/{runid}</div><div class="api-subtitle">Compute and persist environment-adjusted pace values.</div></div>',
        unsafe_allow_html=True,
    )
    runid_pace = st.text_input("Run ID", key="runid_pace")
    if st.button("Compute Pace", use_container_width=True):
        if not runid_pace.strip():
            st.warning("Enter a runid first.")
        else:
            with st.spinner("Calling PUT /pace/{runid} ..."):
                response = requests.put(f"{BASE_URL}/pace/{runid_pace.strip()}", timeout=180)
            parsed = show_response(response, "Pace Response")
            if isinstance(parsed, dict):
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Segments", parsed.get("total_segments", "N/A"))
                c2.metric("Avg Pace", parsed.get("avg_pace_min_per_mile", "N/A"))
                c3.metric("Avg Adjusted", parsed.get("avg_adjusted_pace_min_per_mile", "N/A"))

with tab_heatmap:
    st.markdown(
        '<div class="api-card"><div class="api-title">PUT/GET /heatmap/{runid}</div><div class="api-subtitle">Generate or fetch visualization URL and preview it.</div></div>',
        unsafe_allow_html=True,
    )
    runid_heatmap = st.text_input("Run ID", key="runid_heatmap")
    left, right = st.columns(2)

    with left:
        if st.button("Generate Heatmap (PUT)", use_container_width=True):
            if not runid_heatmap.strip():
                st.warning("Enter a runid first.")
            else:
                with st.spinner("Calling PUT /heatmap/{runid} ..."):
                    response = requests.put(f"{BASE_URL}/heatmap/{runid_heatmap.strip()}", timeout=180)
                parsed = show_response(response, "Heatmap Generation Response")
                if isinstance(parsed, dict) and parsed.get("visualization_url"):
                    viz_url = parsed["visualization_url"]
                    st.components.v1.iframe(viz_url, height=650, scrolling=True)
                    st.caption(f"[Open in new tab]({viz_url})")

    with right:
        if st.button("Get Heatmap (GET)", use_container_width=True):
            if not runid_heatmap.strip():
                st.warning("Enter a runid first.")
            else:
                with st.spinner("Calling GET /heatmap/{runid} ..."):
                    response = requests.get(f"{BASE_URL}/heatmap/{runid_heatmap.strip()}", timeout=120)
                parsed = show_response(response, "Heatmap Fetch Response")
                if isinstance(parsed, dict) and parsed.get("visualization_url"):
                    viz_url = parsed["visualization_url"]
                    st.components.v1.iframe(viz_url, height=650, scrolling=True)
                    st.caption(f"[Open in new tab]({viz_url})")