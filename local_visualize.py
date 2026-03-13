import configparser
import json
import os
import sys

config = configparser.ConfigParser()
config.read(".env")

os.environ['USER_NAME'] = config.get('rds', 'user_name')
os.environ['PASSWORD'] = config.get('rds', 'user_pwd')
os.environ['RDS_PROXY_HOST'] = config.get('rds', 'endpoint')
os.environ['DB_NAME'] = config.get('rds', 'db_name')
os.environ['S3_BUCKET_NAME'] = config.get('s3', 'bucket_name')

os.environ['AWS_DEFAULT_REGION'] = config.get('s3readwrite', 'region_name')
os.environ['AWS_ACCESS_KEY_ID'] = config.get('s3readwrite', 'aws_access_key_id')
os.environ['AWS_SECRET_ACCESS_KEY'] = config.get('s3readwrite', 'aws_secret_access_key')

import webbrowser

import requests

from Lambda_functions.visualize import lambda_handler


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else "1001"

    event = {
        "pathParameters": {"run_id": run_id}
    }

    result = lambda_handler(event, None)
    print(json.dumps(result, indent=2))

    if result.get("statusCode") == 200:
        body = json.loads(result["body"])
        url = body["visualization_url"]
        filename = f"visualization_{run_id}.html"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with open(filename, "wb") as f:
            f.write(resp.content)
        print(f"Map saved to {filename}")
        webbrowser.open(filename)


if __name__ == "__main__":
    main()
