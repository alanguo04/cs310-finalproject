# by Taeyoung Lee
# API 2: Environment-Adjusted Pace Computation
#
# Given a run_id, retrieves enriched segments from RDS, computes
# an environment-adjusted pace for each segment, then writes 
# adjusted_pace back to RDS.
#
# Adjusted pace answers: "What would this segment's pace have been
# under neutral conditions (15°C / 59°F, 50% humidity, flat, no rain)?"
#
# Sources:
#   - Heat: Ely et al. (2008), Med Sci Sports Exerc. Non-elite runners
#     slow ~2% per 5°F (2.78°C) above 59°F (15°C).
#     https://journals.lww.com/acsm-msse/Fulltext/2008/09000/Effect_of_Ambient_Temperature_on_Marathon_Pacing.17.aspx

#   - Humidity: Flouris et al. (2021), Med Sci Sports Exerc. Performance
#     degrades when humidity impairs sweat evaporation, especially >60%.
#     https://pmc.ncbi.nlm.nih.gov/articles/PMC8677617/
#   - Elevation grade: Minetti et al. (2002), J Appl Physiol. Metabolic
#     cost of running increases ~0.6% per 1% grade uphill.
#     https://journals.physiology.org/doi/full/10.1152/japplphysiol.01177.2001
#
#   - Precipitation: 0-2% for rain 
#     https://pubmed.ncbi.nlm.nih.gov/23371827/

import json
import math
import os
import pymysql
import logging
import sys

# rds settings
user_name = os.environ['USER_NAME']
password = os.environ['PASSWORD']
rds_proxy_host = os.environ['RDS_PROXY_HOST']
db_name = os.environ['DB_NAME']

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


###################################################################
#
# Neutral baseline constants
#
NEUTRAL_TEMP_C = 15.0        # 59°F — optimal marathon temperature
NEUTRAL_HUMIDITY = 50.0      # percent


###################################################################
#
# haversine_distance
#
def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Computes the great-circle distance between two GPS points
    using the haversine formula.

    Parameters
    ----------
    lat1, lon1: coordinates of the first point (degrees)
    lat2, lon2: coordinates of the second point (degrees)

    Returns
    -------
    distance in meters between the two points
    """

    R = 6371000  # earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


###################################################################
#
# compute_grade
#
def compute_grade(seg, next_seg):
    """
    Computes the grade (slope as a percentage) between two
    consecutive segments using elevation change and horizontal
    distance.

    Parameters
    ----------
    seg: current segment dict with lat, lon, elevation
    next_seg: next segment dict with lat, lon, elevation

    Returns
    -------
    grade as a percentage (e.g. 5.0 means 5% uphill), or 0.0
    if distance is too small or elevation data is missing
    """

    if seg["elevation"] is None or next_seg["elevation"] is None:
        return 0.0

    horiz_dist = haversine_distance(
        float(seg["lat"]), float(seg["lon"]),
        float(next_seg["lat"]), float(next_seg["lon"])
    )

    if horiz_dist < 1.0:
        return 0.0

    elev_change = float(next_seg["elevation"]) - float(seg["elevation"])

    grade_pct = (elev_change / horiz_dist) * 100.0

    return grade_pct


###################################################################
#
# compute_temperature_factor
#
def compute_temperature_factor(temp_c):
    """
    Computes pace penalty factor due to temperature.

    Based on Ely et al. (2008): non-elite runners slow ~2% per
    5°F (2.78°C) above 59°F (15°C). Below neutral, small benefit
    that caps out. Very cold temps (<0°C) carry slight penalty.

    Parameters
    ----------
    temp_c: temperature in degrees Celsius

    Returns
    -------
    multiplier where >1.0 means conditions are worse than neutral
    """

    diff = temp_c - NEUTRAL_TEMP_C

    if diff > 0:
        #
        # hot: ~2% slower per 2.78°C above neutral
        #
        penalty_per_c = 0.02 / 2.78
        return 1.0 + (diff * penalty_per_c)

    elif diff < -15:
        #
        # very cold (below 0°C): slight penalty returns
        #
        below_zero = abs(temp_c)
        return 1.0 + (below_zero * 0.002)

    else:
        #
        # cool conditions (0-15°C): at or better than neutral,
        # small benefit capped at 1%
        #
        benefit = min(abs(diff) * 0.001, 0.01)
        return 1.0 - benefit


###################################################################
#
# compute_humidity_factor
#
def compute_humidity_factor(humidity, temp_c):
    """
    Computes pace penalty factor due to humidity.

    Humidity mainly matters when it's also hot — high humidity in
    cool weather has minimal impact because sweat evaporation demand
    is lower. Significant impact above 60% RH when temp is elevated.

    Parameters
    ----------
    humidity: relative humidity as a percentage (0-100)
    temp_c: temperature in degrees Celsius

    Returns
    -------
    multiplier where >1.0 means conditions are worse than neutral
    """

    if humidity <= NEUTRAL_HUMIDITY:
        return 1.0

    excess = humidity - NEUTRAL_HUMIDITY

    #
    # scale humidity impact by how hot it is:
    # 0 effect at 10°C, full effect at 30°C
    #
    heat_scaling = max(0.0, (temp_c - 10.0)) / 20.0
    heat_scaling = min(heat_scaling, 1.5)

    #
    # ~1% pace penalty per 10% humidity above 50%, scaled by heat
    #
    penalty = (excess / 10.0) * 0.01 * heat_scaling

    return 1.0 + penalty


###################################################################
#
# compute_grade_factor
#
def compute_grade_factor(grade_pct):
    """
    Computes pace penalty factor due to elevation grade.

    Based on Minetti et al. (2002): metabolic cost of running
    increases roughly 0.6% per 1% grade uphill. Downhill provides
    a benefit up to about -5% grade, after which braking forces
    start to increase metabolic cost again.

    Parameters
    ----------
    grade_pct: grade as a percentage (positive = uphill)

    Returns
    -------
    multiplier where >1.0 means uphill penalty, <1.0 means
    downhill benefit (capped)
    """

    if grade_pct > 0:
        #
        # uphill: ~0.6% slower per 1% grade
        #
        return 1.0 + (grade_pct * 0.006)

    elif grade_pct < -5:
        #
        # steep downhill: benefit caps out around -5% grade,
        # then braking forces reduce efficiency
        #
        benefit_from_mild = 5.0 * 0.003  # benefit from -5% grade
        extra_steep = abs(grade_pct) - 5.0
        braking_penalty = extra_steep * 0.002

        return 1.0 - benefit_from_mild + braking_penalty

    else:
        #
        # mild downhill: ~0.3% faster per 1% grade (less than
        # uphill penalty because gravity assists but braking
        # partially offsets)
        #
        return 1.0 + (grade_pct * 0.003)


###################################################################
#
# compute_precipitation_factor
#
def compute_precipitation_factor(precip_mm):
    """
    Computes pace penalty factor due to precipitation.

    Rain adds weight (wet clothing), reduces traction, and has a
    psychological drag. Rough estimate: ~1-3% depending on intensity.

    Parameters
    ----------
    precip_mm: hourly precipitation in mm from Open-Meteo

    Returns
    -------
    multiplier where >1.0 means conditions are worse than neutral
    """

    if precip_mm is None or precip_mm <= 0:
        return 1.0

    if precip_mm < 1.0:
        return 1.01   # drizzle: ~1%
    elif precip_mm < 5.0:
        return 1.02   # moderate: ~2%
    else:
        return 1.03   # heavy: ~3%, capped


###################################################################
#
# compute_adjusted_pace
#
def compute_adjusted_pace(seg, grade_pct):
    """
    Computes the environment-adjusted pace for a single segment.

    adjusted_pace = actual_pace / total_factor

    If total_factor > 1.0 (bad conditions), adjusted pace is
    FASTER than actual — meaning the runner was performing better
    than the raw number suggests.

    Parameters
    ----------
    seg: dict with pace, temperature, humidity, precipitation
    grade_pct: grade percentage for this segment

    Returns
    -------
    tuple of (adjusted_pace, total_factor), or (None, None) if
    pace data is missing
    """

    pace = seg["pace"]

    if pace is None or pace <= 0:
        return (None, None)

    temp_factor = compute_temperature_factor(float(seg["temperature"]))
    humidity_factor = compute_humidity_factor(float(seg["humidity"]),
                                             float(seg["temperature"]))
    grade_factor = compute_grade_factor(grade_pct)
    precip_factor = compute_precipitation_factor(float(seg["precipitation"]))

    total_factor = temp_factor * humidity_factor * grade_factor * precip_factor

    adjusted = float(pace) / total_factor

    return (round(adjusted, 2), round(total_factor, 6))


###################################################################
#
# lambda_handler
#
def lambda_handler(event, context):
    """
    AWS Lambda entry point for API 2.

    Expects event body: { "run_id": <int> }

    Retrieves enriched segments from RDS for the given run_id,
    computes environment-adjusted pace for each segment, updates
    RDS with adjusted_pace values, and returns summary statistics.

    Parameters
    ----------
    event: API Gateway event with body containing run_id
    context: Lambda context (unused)

    Returns
    -------
    response dict with statusCode and JSON body containing summary
    """

    try:
        body = json.loads(event["body"])

        run_id = body.get("run_id")

        if run_id is None:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "missing run_id"})
            }

        #
        # fetch all segments for this run, ordered by time
        #
        with conn.cursor(pymysql.cursors.DictCursor) as cur:

            sql_select = """
                SELECT lat, lon, time, elevation, temperature,
                       humidity, precipitation, pace
                FROM runsegments
                WHERE runid = %s
                ORDER BY time ASC
            """

            cur.execute(sql_select, (run_id,))
            segments = cur.fetchall()

        if len(segments) == 0:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "error": f"no segments found for run_id {run_id}"
                })
            }

        #
        # compute adjusted pace for each segment
        #
        updates = []

        for i, seg in enumerate(segments):

            if i < len(segments) - 1:
                grade = compute_grade(seg, segments[i + 1])
            else:
                grade = 0.0

            adjusted_pace, total_factor = compute_adjusted_pace(seg, grade)

            updates.append((adjusted_pace, seg["lat"], seg["lon"], seg["time"]))

        #
        # batch update — parameterized queries to prevent SQL injection
        #
        with conn.cursor() as cur:

            sql_update = """
                UPDATE runsegments
                SET adjusted_pace = %s
                WHERE runid = %s
                  AND lat = %s
                  AND lon = %s
                  AND time = %s
            """

            for upd in updates:
                cur.execute(sql_update, (upd[0], run_id, upd[1], upd[2], upd[3]))

        conn.commit()

        #
        # compute summary stats (filter out stops/cooldown >15 min/mile)
        #
        valid_paces = []
        valid_adjusted = []

        for i, seg in enumerate(segments):
            if seg["pace"] is not None and float(seg["pace"]) < 15:
                valid_paces.append(float(seg["pace"]))
                if updates[i][0] is not None:
                    valid_adjusted.append(updates[i][0])

        if len(valid_paces) > 0 and len(valid_adjusted) > 0:

            avg_pace = sum(valid_paces) / len(valid_paces)
            avg_adjusted = sum(valid_adjusted) / len(valid_adjusted)
            avg_factor = avg_pace / avg_adjusted if avg_adjusted > 0 else 1.0

            summary = {
                "run_id": run_id,
                "total_segments": len(segments),
                "valid_segments": len(valid_paces),
                "avg_pace_min_per_mile": round(avg_pace, 2),
                "avg_adjusted_pace_min_per_mile": round(avg_adjusted, 2),
                "avg_environment_factor": round(avg_factor, 4),
                "pct_slower_from_conditions": round((avg_factor - 1) * 100, 2)
            }
        else:
            summary = {
                "run_id": run_id,
                "error": "no valid segments with pace data"
            }

        return {
            "statusCode": 200,
            "body": json.dumps(summary)
        }

    except Exception as err:
        logging.error("lambda_handler():")
        logging.error(str(err))

        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(err)})
        }
