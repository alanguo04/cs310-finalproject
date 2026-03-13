import json
import requests


BASE_URL = "https://urv3reouhh.execute-api.us-east-2.amazonaws.com/prod"


def main():
    runid = input("Run ID? ").strip()
    if not runid:
        raise ValueError("Run ID is required")

    url = f"{BASE_URL}/heatmap/{runid}"
    print(f"Calling PUT {url}")

    response = requests.put(url, timeout=120)
    print("Status code:", response.status_code)

    try:
        payload = response.json()
    except Exception:
        print(response.text)
        return

    result = json.loads(payload["body"]) if isinstance(payload, dict) and "body" in payload else payload
    print(json.dumps(result, indent=2))

    if isinstance(result, dict) and "visualization_url" in result:
        print("\nVisualization URL:")
        print(result["visualization_url"])


if __name__ == "__main__":
    main()
