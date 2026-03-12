import base64
import json
import sys
from pathlib import Path

from Lambda_functions.gpxparser import lambda_handler


def main():
    file_path = Path(sys.argv[1] if len(sys.argv) > 1 else "Surf_City_Half.gpx")
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    payload = {
        "filename": file_path.name,
        "file": base64.b64encode(file_path.read_bytes()).decode("utf-8"),
    }
    event = {"body": json.dumps(payload)}

    result = lambda_handler(event, None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
