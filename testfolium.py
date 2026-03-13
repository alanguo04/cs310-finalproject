import folium
import numpy as np
import json

with open("enriched_segments.json", "r", encoding="utf-8") as infile:
    rows = json.load(infile)

# list of (lat, lon, pace_min_per_mile)
segments = [
    (row["lat"], row["lon"], row.get("pace_min_per_mile"))
    for row in rows
    if row.get("lat") is not None and row.get("lon") is not None
]

if len(segments) < 2:
    raise ValueError("Need at least 2 segment points in enriched_segments.json")

def pace_to_color(pace, min_pace=7.5, max_pace=10.5):
    """Green (fast) → Yellow → Red (slow)"""
    if pace is None:
        return "#888888"
    t = (pace - min_pace) / (max_pace - min_pace)
    t = max(0, min(1, t))
    r = int(255 * t)
    g = int(255 * (1 - t))
    return f"#{r:02x}{g:02x}00"

# Center map on midpoint
center_lat = np.mean([s[0] for s in segments])
center_lon = np.mean([s[1] for s in segments])
m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="CartoDB positron")

# Draw colored segments between consecutive points
for i in range(len(segments) - 1):
    lat1, lon1, pace1 = segments[i]
    lat2, lon2, _ = segments[i + 1]
    color = pace_to_color(pace1)
    pace_label = "N/A" if pace1 is None else f"{pace1:.2f}"
    folium.PolyLine(
        locations=[[lat1, lon1], [lat2, lon2]],
        color=color,
        weight=5,
        opacity=0.9,
        tooltip=f"Pace: {pace_label} min/mi"
    ).add_to(m)

# Start / end markers
folium.CircleMarker(segments[0][:2],  radius=7, color="green", fill=True, tooltip="Start").add_to(m)
folium.CircleMarker(segments[-1][:2], radius=7, color="red",   fill=True, tooltip="End").add_to(m)

m.save("run_map.html")