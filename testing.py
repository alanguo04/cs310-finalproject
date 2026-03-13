import base64
from pathlib import Path

filepath = "Surf_City_Half.gpx"
filepath = Path(filepath)
if not filepath.is_file():
    raise FileNotFoundError(f"File not found: {filepath}")
file_bytes = filepath.read_bytes()
encoded_file = base64.b64encode(file_bytes).decode("utf-8")
print(encoded_file)