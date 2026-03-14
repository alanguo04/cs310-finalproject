import json
import pymysql
import os
import logging
import sys

# decimal types aren't serializable 
from decimal import Decimal

def decimal_serializer(obj):
    if isinstance(obj, Decimal):
        return str(obj) 
    raise TypeError("Object of type %s is not JSON serializable" % type(obj).__name__)

# rds settings
user_name = os.environ['USER_NAME']
password = os.environ['PASSWORD']
rds_proxy_host = os.environ['RDS_PROXY_HOST']
db_name = os.environ['DB_NAME']

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    try:
        conn = pymysql.connect(host=rds_proxy_host, user=user_name, passwd=password, db=db_name, connect_timeout=5)
    except pymysql.MySQLError as e:
        logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
        logger.error(e)
        sys.exit(1)

    logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")
    try:
        run_id = event.get("pathParameters", {}).get("runid")
        
        if not run_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing runid"})
            }

        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # Check run exists
            cur.execute("SELECT runid FROM runs WHERE runid = %s", (run_id,))
            run = cur.fetchone()

            if not run:
                return {
                    "statusCode": 404,
                    "body": json.dumps({"error": f"Run {run_id} not found"})
                }

            cur.execute("""
                SELECT runid, lat, lon, time, elevation,
                       temperature, humidity, precipitation,
                       pace, adjusted_pace
                FROM runsegments
                WHERE runid = %s
            """, (run_id,))
            segments = cur.fetchall()

        # Convert datetime objects to strings
        for seg in segments:
            if seg.get("time") and hasattr(seg["time"], "isoformat"):
                seg["time"] = seg["time"].isoformat()
                
        return {
            "statusCode": 200,
            "body": json.dumps({
                "run_id": run_id,
                "segments": segments
            }, default=decimal_serializer)
        }

    except Exception as e:
        logger.error(f"ERROR: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Internal server error: {e}"})
        }