import json
import os
import sys
import logging
import io
from decimal import Decimal

import pymysql
import boto3
import folium

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


def fetch_segments(run_id):

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            "SELECT lat, lon, pace, adjusted_pace FROM runsegments WHERE runid = %s ORDER BY time ASC",
            (run_id,)
        )
        rows = cur.fetchall()

    if not rows:
        return None

    for row in rows:
        for key in row:
            if isinstance(row[key], Decimal):
                row[key] = float(row[key])

    return rows


def pace_to_hex(pace_value, pace_min, pace_max):

    if pace_value is None or pace_min is None or pace_max is None:
        return "#808080"

    if pace_max == pace_min:
        return "#00ff00"

    t = (pace_value - pace_min) / (pace_max - pace_min)
    t = max(0.0, min(1.0, t))

    if t <= 0.5:
        ratio = t / 0.5
        r = int(255 * ratio)
        g = 255
    else:
        ratio = (t - 0.5) / 0.5
        r = 255
        g = int(255 * (1 - ratio))

    return f"#{r:02x}{g:02x}00"


def build_map(segments, pace_min, pace_max):

    lats = [s['lat'] for s in segments]
    lons = [s['lon'] for s in segments]
    center_lat = (min(lats) + max(lats)) / 2
    center_lon = (min(lons) + max(lons)) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles="OpenStreetMap")

    for i in range(len(segments) - 1):
        seg_start = segments[i]
        seg_end = segments[i + 1]

        pace_val = seg_end.get('adjusted_pace') or seg_end.get('pace')
        color = pace_to_hex(pace_val, pace_min, pace_max)

        folium.PolyLine(
            locations=[
                [seg_start['lat'], seg_start['lon']],
                [seg_end['lat'], seg_end['lon']],
            ],
            color=color,
            weight=5,
            opacity=0.85,
        ).add_to(m)

    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

    return m


def upload_to_s3(html_bytes, run_id):

    key = f"visualizations/{run_id}.html"

    s3_client.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=html_bytes,
        ContentType='text/html',
    )

    presigned_url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': s3_bucket, 'Key': key},
        ExpiresIn=604800
    )

    return presigned_url


def update_visualization_link(run_id):

    s3_uri = f"s3://{s3_bucket}/visualizations/{run_id}.html"

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE runs SET visualizationlink = %s WHERE runid = %s",
            (s3_uri, run_id)
        )
    conn.commit()


def lambda_handler(event, context):

    try:
        run_id = event.get('pathParameters', {}).get('run_id')

        if not run_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing run_id path parameter"})
            }

        try:
            run_id = int(run_id)
        except ValueError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "run_id must be an integer"})
            }

        # 1: fetch segments from DB
        conn.ping(reconnect=True)
        segments = fetch_segments(run_id)
        if not segments:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": f"No segments found for run_id {run_id}"})
            }

        if len(segments) < 2:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Need at least 2 segments to visualize"})
            }

        # 2: compute pace range for color mapping
        pace_values = []
        for s in segments:
            p = s.get('adjusted_pace') or s.get('pace')
            if p is not None:
                pace_values.append(p)

        if not pace_values:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No pace data available for this run"})
            }

        pace_min = min(pace_values)
        pace_max = max(pace_values)

        # 3: build folium map with color-coded route
        m = build_map(segments, pace_min, pace_max)
        html_bytes = m._repr_html_().encode('utf-8')

        # 4: upload to S3
        presigned_url = upload_to_s3(html_bytes, run_id)

        # 5: update DB with visualization link
        update_visualization_link(run_id)

        # 6: return URL to client
        return {
            "statusCode": 200,
            "body": json.dumps({
                "run_id": run_id,
                "visualization_url": presigned_url,
                "segments_visualized": len(segments)
            })
        }

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
