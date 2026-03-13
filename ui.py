import base64
import json

import requests
import streamlit as st


BASE_URL = "https://urv3reouhh.execute-api.us-east-2.amazonaws.com/prod"
API_URL = BASE_URL + "/final"


st.title("GPX Upload")
uploaded_file = st.file_uploader("Choose a GPX file", type=["gpx"])

if st.button("Upload and Process"):
    if uploaded_file is None:
        st.warning("Please choose a GPX file first.")
    else:
        file_bytes = uploaded_file.read()
        payload = {
            "filename": uploaded_file.name,
            "file": base64.b64encode(file_bytes).decode("utf-8"),
        }

        with st.spinner("Sending to API Gateway and waiting for response..."):
            response = requests.post(API_URL, json=payload, timeout=300)

        st.write("Status code:", response.status_code)

        try:
            raw_json = response.json()
        except Exception:
            st.text(response.text)
        else:
            if isinstance(raw_json, dict) and "body" in raw_json:
                try:
                    parsed = json.loads(raw_json["body"])
                except Exception:
                    parsed = raw_json
            else:
                parsed = raw_json

            st.json(parsed)

st.divider()
st.subheader("Route Visualization")
run_id_input = st.text_input("Enter Run ID to visualize")

if st.button("Generate Visualization"):
    if not run_id_input:
        st.warning("Please enter a Run ID.")
    else:
        viz_url = f"{BASE_URL}/final/visualize/{run_id_input}"

        with st.spinner("Generating route visualization..."):
            viz_response = requests.get(viz_url, timeout=120)

        if viz_response.status_code == 200:
            viz_data = viz_response.json()

            if isinstance(viz_data, dict) and "body" in viz_data:
                try:
                    viz_data = json.loads(viz_data["body"])
                except Exception:
                    pass

            image_url = viz_data.get("visualization_url")
            if image_url:
                st.image(image_url, caption=f"Run {run_id_input} - Route Visualization")
                st.success(f"Segments visualized: {viz_data.get('segments_visualized')}")
        else:
            st.error(f"Failed: {viz_response.status_code}")
            try:
                st.json(viz_response.json())
            except Exception:
                st.text(viz_response.text)
