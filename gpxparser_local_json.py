import json
import sys
from datetime import timedelta
from pathlib import Path

import gpxpy
import requests


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

                points.append(
                    {
                        "lat": p.latitude,
                        "lon": p.longitude,
                        "time": p.time,
                        "elevation": p.elevation,
                    }
                )

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
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation",
    }

    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
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

        enriched.append(
            {
                "lat": seg["lat"],
                "lon": seg["lon"],
                "time": seg["time"].isoformat(),
                "elevation": seg["elevation"],
                "temperature": weather["temperature_2m"][weather_idx],
                "humidity": weather["relative_humidity_2m"][weather_idx],
                "precipitation": weather["precipitation"][weather_idx],
                "pace_min_per_mile": pace_minutes_per_mile,
            }
        )

    return enriched


def store_locally(segments, output_path="enriched_segments.json"):
    with open(output_path, "w", encoding="utf-8") as outfile:
        json.dump(segments, outfile, indent=2)


def main():
    gpx_path = Path(sys.argv[1] if len(sys.argv) > 1 else "short.gpx")
    output_path = Path(sys.argv[2] if len(sys.argv) > 2 else "enriched_segments.json")

    if not gpx_path.is_file():
        raise FileNotFoundError(f"File not found: {gpx_path}")

    gpx_text = gpx_path.read_text(encoding="utf-8")
    points = parse_gpx(gpx_text)
    segments = segment_points(points)
    enriched_segments = enrich_segments(segments)
    store_locally(enriched_segments, str(output_path))

    print(f"Wrote {len(enriched_segments)} segments to {output_path}")


if __name__ == "__main__":
    main()
