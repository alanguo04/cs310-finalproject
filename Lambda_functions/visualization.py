import json
import os
import sys
import logging
from decimal import Decimal

import pymysql
import boto3

# rds settings
user_name = os.environ['USER_NAME']
password = os.environ['PASSWORD']
rds_proxy_host = os.environ['RDS_PROXY_HOST']
db_name = os.environ['DB_NAME']
s3_bucket = os.environ['S3_BUCKET']
mapbox_token = os.environ['MPBX_TOKEN']

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


def fetch_segments(runid):

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            "SELECT lat, lon, pace, adjusted_pace FROM runsegments WHERE runid = %s ORDER BY time ASC",
            (runid,)
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


def build_map_html(segments, pace_min, pace_max):

    lats = [s['lat'] for s in segments]
    lons = [s['lon'] for s in segments]
    center_lat = (min(lats) + max(lats)) / 2
    center_lon = (min(lons) + max(lons)) / 2

    features = []
    for i in range(len(segments) - 1):
        seg_start = segments[i]
        seg_end = segments[i + 1]
        pace_val = seg_end.get('adjusted_pace') or seg_end.get('pace')
        color = pace_to_hex(pace_val, pace_min, pace_max)
        features.append({
            "type": "Feature",
            "properties": {"color": color},
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [seg_start['lon'], seg_start['lat']],
                    [seg_end['lon'], seg_end['lat']],
                ]
            }
        })

    geojson = json.dumps({"type": "FeatureCollection", "features": features})
    bounds_js = json.dumps([
        [min(lons), min(lats)],
        [max(lons), max(lats)]
    ])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script src="https://api.mapbox.com/mapbox-gl-js/v3.4.0/mapbox-gl.js"></script>
<link href="https://api.mapbox.com/mapbox-gl-js/v3.4.0/mapbox-gl.css" rel="stylesheet"/>
<style>body{{margin:0}}#map{{width:100%;height:100vh}}</style>
</head>
<body>
<div id="map"></div>
<script>
mapboxgl.accessToken='{mapbox_token}';
const map=new mapboxgl.Map({{container:'map',style:'mapbox://styles/mapbox/streets-v12',center:[{center_lon},{center_lat}],zoom:13}});
map.addControl(new mapboxgl.NavigationControl());
map.on('load',()=>{{
  const data={geojson};
  data.features.forEach((f,i)=>{{
    const id='seg-'+i;
    map.addSource(id,{{type:'geojson',data:f}});
    map.addLayer({{id:id,type:'line',source:id,paint:{{'line-color':f.properties.color,'line-width':5,'line-opacity':0.85}}}});
  }});
  map.fitBounds({bounds_js},{{padding:40}});
}});
</script>
</body>
</html>"""


def upload_to_s3(html_bytes, runid):

    key = f"visualizations/{runid}.html"

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


def update_visualization_link(runid):

    s3_uri = f"visualizations/{runid}.html"

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE runs SET visualizationlink = %s WHERE runid = %s",
            (s3_uri, runid)
        )
    conn.commit()


def lambda_handler(event, context):

    try:
        runid = event.get('pathParameters', {}).get('runid')

        if not runid:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing runid path parameter"})
            }

        try:
            runid = int(runid)
        except ValueError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "runid must be an integer"})
            }

        # 1: fetch segments from DB
        conn.ping(reconnect=True)
        segments = fetch_segments(runid)
        if not segments:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": f"No segments found for runid {runid}"})
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

        # 3: build mapbox map with color-coded route
        html_str = build_map_html(segments, pace_min, pace_max)
        html_bytes = html_str.encode('utf-8')

        # 4: upload to S3
        presigned_url = upload_to_s3(html_bytes, runid)

        # 5: update DB with visualization link
        update_visualization_link(runid)

        # 6: return URL to client
        return {
            "statusCode": 200,
            "body": json.dumps({
                "runid": runid,
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
