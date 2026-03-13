import base64
import json

import requests
import streamlit as st


API_URL = "https://urv3reouhh.execute-api.us-east-2.amazonaws.com/prod/final"


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
