import configparser
import json
import os

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

from Lambda_functions.delete_run import lambda_handler


def main():
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
