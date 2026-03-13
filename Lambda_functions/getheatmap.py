import json
import pymysql
import boto3
import os
import logging
import sys

user_name = os.environ['USER_NAME']
password = os.environ['PASSWORD']
rds_proxy_host = os.environ['RDS_PROXY_HOST']
db_name = os.environ['DB_NAME']
s3_bucket = os.environ['S3_BUCKET']

logger = logging.getLogger()
logger.setLevel(logging.INFO)

try:
    conn = pymysql.connect(host=rds_proxy_host, user=user_name, passwd=password, db=db_name, connect_timeout=5)
except pymysql.MySQLError as e:
    logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
    logger.error(e)
    sys.exit(1)

s3 = boto3.client('s3')

def lambda_handler(event, context):
    try:
        run_id = event.get("pathParameters", {}).get("runid")

        if not run_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing runid"})
            }

        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT visualizationlink FROM runs WHERE runid = %s", (run_id,))
            run = cur.fetchone()

        if not run:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Run {run_id} not found"})
            }

        viz_link = run["visualizationlink"]

        if viz_link is None:
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "run_id": run_id,
                    "visualization": None,
                    "message": "Visualization not yet generated for this run"
                })
            }

        # Generate a presigned URL so the client can access the private S3 object
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": s3_bucket, "Key": viz_link},
            ExpiresIn=3600
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "run_id": run_id,
                "visualization_url": presigned_url
            })
        }

    except Exception as e:
        logger.error(f"ERROR: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }
