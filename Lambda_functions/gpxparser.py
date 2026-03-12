# https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-lambda-tutorial.html

import json
import base64
import uuid
import requests
import gpxpy
# import boto3

from datetime import timedelta
from datetime import datetime

# dynamodb = boto3.resource("dynamodb")
# table = dynamodb.Table("runs")

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


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
                    "time": p.time
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

    for seg in segments:

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
            idx = times.index(hour.strftime("%Y-%m-%dT%H:00"))
        except ValueError:
            continue

        enriched.append({
            "lat": seg["lat"],
            "lon": seg["lon"],
            "time": seg["time"].isoformat(),
            "temperature": weather["temperature_2m"][idx],
            "humidity": weather["relative_humidity_2m"][idx],
            "wind_speed": weather["wind_speed_10m"][idx],
            "wind_direction": weather["wind_direction_10m"][idx],
            "precipitation": weather["precipitation"][idx]
        })

    return enriched


def store_run(run_id, segments):

    table.put_item(
        Item={
            "run_id": run_id,
            "segments": segments
        }
    )


def lambda_handler(event, context):

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

    run_id = str(uuid.uuid4())

    # store_run(run_id, enriched_segments)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "run_id": run_id,
            "segments_processed": len(enriched_segments)
        }),
        "data": enriched_segments
    }