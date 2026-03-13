import json
import os
import sys
import logging

import pymysql
import boto3

# rds settings
user_name = os.environ['USER_NAME']
password = os.environ['PASSWORD']
rds_proxy_host = os.environ['RDS_PROXY_HOST']
db_name = os.environ['DB_NAME']
s3_bucket = os.environ['S3_BUCKET_NAME']

logger = logging.getLogger()
logger.setLevel(logging.INFO)

try:
    conn = pymysql.connect(host=rds_proxy_host, user=user_name, passwd=password, db=db_name, connect_timeout=5)
except pymysql.MySQLError as e:
    logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
    logger.error(e)
    sys.exit(1)

logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")

s3_client = boto3.client('s3')


def delete_all_s3_visualizations():

    deleted = 0
    paginator = s3_client.get_paginator('list_objects_v2')

    for page in paginator.paginate(Bucket=s3_bucket, Prefix='visualizations/'):
        objects = page.get('Contents', [])
        if not objects:
            continue

        s3_client.delete_objects(
            Bucket=s3_bucket,
            Delete={'Objects': [{'Key': obj['Key']} for obj in objects]}
        )
        deleted += len(objects)

    logger.info(f"Deleted {deleted} S3 objects")
    return deleted


def delete_all_from_db():

    conn.begin()

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM runsegments")
            segments_deleted = cur.rowcount

            cur.execute("DELETE FROM runs")
            runs_deleted = cur.rowcount

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return runs_deleted, segments_deleted


def lambda_handler(event, context):

    try:
        conn.ping(reconnect=True)

        # 1: delete all from RDS (transactional)
        runs_deleted, segments_deleted = delete_all_from_db()

        # 2: delete all visualizations from S3
        s3_deleted = delete_all_s3_visualizations()

        return {
            "statusCode": 200,
            "body": json.dumps({
                "runs_deleted": runs_deleted,
                "segments_deleted": segments_deleted,
                "s3_objects_deleted": s3_deleted,
            })
        }

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
