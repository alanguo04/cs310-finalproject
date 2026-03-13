import requests
import pathlib
import sys
import base64
import json

# eliminate traceback so we just get error message:
sys.tracebacklimit = 0

baseurl = "https://urv3reouhh.execute-api.us-east-2.amazonaws.com/prod"
url = baseurl + "/final"

# filename = input("GPX filename? ")
# filename= "short.gpx"
filename = "Surf_City_Half.gpx"
filepath = pathlib.Path(filename)

if not filepath.is_file():
  print(f"**Error: file '{filename}' does not exist...")
  sys.exit(0)

if filepath.suffix.lower() != ".gpx":
  print("**Error: file must end with .gpx")
  sys.exit(0)

file_bytes = filepath.read_bytes()
encoded_file = base64.b64encode(file_bytes).decode("utf-8")

data = {
  "filename": filepath.name,
  "file": encoded_file
}

print(f"Calling API Gateway for '{filename}'...")

response = requests.post(url, json=data)

if response.status_code != 200:
  print("**ERROR: failed with status code:", response.status_code)
  try:
    print(response.json())
  except Exception:
    print(response.text)
  sys.exit(0)

body = response.json()

print("Run ID:", body["run_id"])