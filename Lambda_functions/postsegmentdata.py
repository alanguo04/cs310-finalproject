# https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-lambda-tutorial.html

# NOTE TODO
# Remove store_locally and add store_run functions

import json
import base64
import requests
import gpxpy
import os
import pymysql
import logging
import sys

# rds settings
user_name = os.environ['USER_NAME']
password = os.environ['PASSWORD']
rds_proxy_host = os.environ['RDS_PROXY_HOST']
db_name = os.environ['DB_NAME']

from datetime import timedelta
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# create the database connection outside of the handler to allow connections to be
# re-used by subsequent function invocations.
try:
    conn = pymysql.connect(host=rds_proxy_host, user=user_name, passwd=password, db=db_name, connect_timeout=5)
except pymysql.MySQLError as e:
    logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
    logger.error(e)
    sys.exit(1)

logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


def calculate_pace_minutes_per_mile(start_segment, end_segment):

    elapsed_seconds = (end_segment["time"] - start_segment["time"]).total_seconds()
    if elapsed_seconds <= 0:
        return None

    distance_meters = gpxpy.geo.haversine_distance(
        start_segment["lat"],
        start_segment["lon"],
        end_segment["lat"],
        end_segment["lon"],
    )
    if distance_meters <= 0:
        return None

    miles = distance_meters / 1609.344
    return (elapsed_seconds / 60.0) / miles


def parse_gpx(gpx_content):

    gpx = gpxpy.parse(gpx_content)

    points = []

    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:

                if p.time is None:
                    continue

                points.append({
                    "lat": p.latitude,
                    "lon": p.longitude,
                    "time": p.time,
                    "elevation": p.elevation
                })

    return points


def segment_points(points):

    segments = []

    last_time = None

    for p in points:

        if last_time is None:
            segments.append(p)
            last_time = p["time"]
            continue

        if p["time"] - last_time >= timedelta(seconds=30):
            segments.append(p)
            last_time = p["time"]

    return segments

def get_weather(lat, lon, date):

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date,
        "end_date": date,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation"
    }

    resp = requests.get(OPEN_METEO_URL, params=params)
    resp.raise_for_status()

    return resp.json()["hourly"]

def enrich_segments(segments):

    weather_cache = {}

    enriched = []

    for seg_idx, seg in enumerate(segments):

        lat = round(seg["lat"], 2)
        lon = round(seg["lon"], 2)

        t = seg["time"]

        hour = t.replace(minute=0, second=0, microsecond=0)

        key = (lat, lon, hour)

        if key not in weather_cache:

            date = hour.strftime("%Y-%m-%d")
            weather_cache[key] = get_weather(lat, lon, date)

        weather = weather_cache[key]

        times = weather["time"]
        
        try:
            weather_idx = times.index(hour.strftime("%Y-%m-%dT%H:00"))
        except ValueError:
            continue

        pace_minutes_per_mile = None
        if len(segments) >= 2:
            if seg_idx == 0:
                pace_minutes_per_mile = calculate_pace_minutes_per_mile(segments[0], segments[1])
            else:
                pace_minutes_per_mile = calculate_pace_minutes_per_mile(segments[seg_idx - 1], segments[seg_idx])

        enriched.append({
            "lat": seg["lat"],
            "lon": seg["lon"],
            "time": seg["time"].isoformat(),
            "elevation": seg["elevation"],
            "temperature": weather["temperature_2m"][weather_idx],
            "humidity": weather["relative_humidity_2m"][weather_idx],
            # "wind_speed": weather["wind_speed_10m"][weather_idx],
            # "wind_direction": weather["wind_direction_10m"][weather_idx],
            "precipitation": weather["precipitation"][weather_idx],
            "pace_min_per_mile": pace_minutes_per_mile
        })

    return enriched

def store_run(segments):

    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (runid) VALUES (NULL); ")
        cur.execute("SELECT LAST_INSERT_ID();")
        runid = cur.fetchone()
        sqlquery = """
              INSERT INTO runsegments (runid, 
                lat, 
                lon, 
                time, 
                elevation,
                temperature, 
                humidity, 
                precipitation,
                pace, 
                adjusted_pace)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL);
              """
        for seg in segments:
            cur.execute(sqlquery, (runid,
                            seg["lat"],
                            seg["lon"],
                            seg["time"],
                            seg["elevation"],
                            seg["temperature"],
                            seg["humidity"],
                            seg["precipitation"],
                            seg["pace_min_per_mile"],))
        
    conn.commit()
    return runid


def lambda_handler(event, context):
    # logger.info("1")
    body = json.loads(event["body"])

    filename = body["filename"]
    file_data = base64.b64decode(body["file"])

    if not filename.endswith(".gpx"):
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Only GPX supported"})
        }
    gpx_text = file_data.decode("utf-8")

    points = parse_gpx(gpx_text)

    segments = segment_points(points)

    enriched_segments = enrich_segments(segments)

    run_id = store_run(enriched_segments)
    return {
        "statusCode": 200,
        "body": json.dumps({
            "run_id": run_id,
        }),
    }