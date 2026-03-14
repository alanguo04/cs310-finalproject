# by Taeyoung Lee
# API 2: Environment-Adjusted Pace Computation
#
# takes a runid, retrieves enriched segments from RDS
# computes an environment-adjusted pace for each segment, then writes adjusted_pace back to RDS.
#
# environment-adjusted pace accounts for what the segment's pace would have been under neutral conitions (15°C / 59°F, 50% humidity, flat, no rain).
#
# Sources:
#   - HEAT: https://journals.lww.com/acsm-msse/Fulltext/2008/09000/Effect_of_Ambient_Temperature_on_Marathon_Pacing.17.aspx
#     slow roughly 2% per 5°F (2.78°C) above 59°F (15°C).

#   - HUMIDITY: https://pmc.ncbi.nlm.nih.gov/articles/PMC8677617/
#     degrades when humidity impairs sweat evaporation, especially >60%.

#   - ELEVATION GRADE: https://journals.physiology.org/doi/full/10.1152/japplphysiol.01177.2001
#     cost of running increases ~0.6% per 1% grade uphill.
#
#   - PRECIPITATION: https://pubmed.ncbi.nlm.nih.gov/23371827/
#     0-2% for rain


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


# neutral baseline constants
NEUTRAL_TEMP_C = 15.0 # 59 F
NEUTRAL_HUMIDITY = 50.0 # percent


def haversine_distance(lat1, lon1, lat2, lon2):
    # great-circle distance between two GPS points in meters
    R = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def compute_grade(seg, next_seg):
    # grade (slope %) between two consecutive segments
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


def compute_temperature_factor(temp_c):
    # pace penalty from temperature
    # roughly 2% slower per 2.78C above neutral
    diff = temp_c - NEUTRAL_TEMP_C

    if diff > 0:
        # hot
        penalty_per_c = 0.02 / 2.78
        return 1.0 + (diff * penalty_per_c)

    elif diff < -15:
        # very cold (below 0C), slight penalty
        below_zero = abs(temp_c)
        return 1.0 + (below_zero * 0.002)

    else:
        # cool (0-15C), small benefit capped at 1%
        benefit = min(abs(diff) * 0.001, 0.01)
        return 1.0 - benefit


def compute_humidity_factor(humidity, temp_c):
    # pace penalty from humidity, only matters when its hot
    if humidity <= NEUTRAL_HUMIDITY:
        return 1.0

    excess = humidity - NEUTRAL_HUMIDITY

    # scale by how hot it is (0 effect at 10C, full at 30C)
    heat_scaling = max(0.0, (temp_c - 10.0)) / 20.0
    heat_scaling = min(heat_scaling, 1.5)

    # roughly 1% per 10% humidity above 50%, scaled by heat
    penalty = (excess / 10.0) * 0.01 * heat_scaling

    return 1.0 + penalty


def compute_grade_factor(grade_pct):
    # pace penalty from elevation grade 
    # roughly 0.6% slower per 1% grade uphill
    if grade_pct > 0:
        return 1.0 + (grade_pct * 0.006)

    elif grade_pct < -5:
        # steep downhill: benefit caps out and braking forces kick in
        benefit_from_mild = 5.0 * 0.003
        extra_steep = abs(grade_pct) - 5.0
        braking_penalty = extra_steep * 0.002
        return 1.0 - benefit_from_mild + braking_penalty

    else:
        # mild downhill: roughly 0.3% faster per 1% grade
        return 1.0 + (grade_pct * 0.003)


def compute_precipitation_factor(precip_mm):
    # pace penalty from rain
    if precip_mm is None or precip_mm <= 0:
        return 1.0

    if precip_mm < 1.0:
        return 1.01   # drizzle 1%
    elif precip_mm < 5.0:
        return 1.02   # moderate 2%
    else:
        return 1.03   # heavy 3%, capped upperbound


def compute_adjusted_pace(seg, grade_pct):
    # adjusted_pace = actual_pace / total_factor
    # if factor > 1.0 (bad conditions), adjusted is faster than actual
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


def lambda_handler(event, context):
    # create the database connection outside of the handler to allow connections to be
    # re-used by subsequent function invocations.
    try:
        conn = pymysql.connect(host=rds_proxy_host, user=user_name, passwd=password, db=db_name, connect_timeout=5)
    except pymysql.MySQLError as e:
        logger.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
        logger.error(e)
        sys.exit(1)

    logger.info("SUCCESS: Connection to RDS for MySQL instance succeeded")
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

        # fetch all segments for this run
        with conn.cursor(pymysql.cursors.DictCursor) as cur:

            sql_select = """
                SELECT lat, lon, time, elevation, temperature,
                       humidity, precipitation, pace
                FROM runsegments
                WHERE runid = %s
                ORDER BY time ASC
            """

            cur.execute(sql_select, (runid,))
            segments = cur.fetchall()

        if len(segments) == 0:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "error": f"no segments found for runid {runid}"
                })
            }

        # compute adjusted pace for each segment
        updates = []

        for i, seg in enumerate(segments):

            if i < len(segments) - 1:
                grade = compute_grade(seg, segments[i + 1])
            else:
                grade = 0.0

            adjusted_pace, total_factor = compute_adjusted_pace(seg, grade)

            updates.append((adjusted_pace, seg["lat"], seg["lon"], seg["time"]))

        # batch update
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
                cur.execute(sql_update, (upd[0], runid, upd[1], upd[2], upd[3]))

        conn.commit()

        # summary stats, filter out stops/cooldown >15 min/mile
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
                "runid": runid,
                "total_segments": len(segments),
                "valid_segments": len(valid_paces),
                "avg_pace_min_per_mile": round(avg_pace, 2),
                "avg_adjusted_pace_min_per_mile": round(avg_adjusted, 2),
                "avg_environment_factor": round(avg_factor, 4),
                "pct_slower_from_conditions": round((avg_factor - 1) * 100, 2)
            }
        else:
            summary = {
                "runid": runid,
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
