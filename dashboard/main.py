"""
Dashboard API Service (Cloud Run)
Serves JSON endpoints consumed by the frontend dashboard.
"""

import os
import logging
from flask import Flask, jsonify, send_from_directory
from google.cloud import bigquery
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
CORS(app)

PROJECT_ID    = os.environ["GCP_PROJECT_ID"]
DATASET_ID    = os.environ.get("BQ_DATASET", "anomaly_detection")
bq            = bigquery.Client(project=PROJECT_ID)


def run_query(sql: str) -> list[dict]:
    return [dict(r) for r in bq.query(sql).result()]


@app.route("/api/anomalies/recent")
def recent_anomalies():
    sql = f"""
        SELECT detected_at, sensor_id, metric, value, mean, std_dev,
               z_score, severity, ai_explanation
        FROM `{PROJECT_ID}.{DATASET_ID}.anomalies`
        ORDER BY detected_at DESC
        LIMIT 50
    """
    rows = run_query(sql)
    # Convert timestamps to strings
    for r in rows:
        if hasattr(r.get("detected_at"), "isoformat"):
            r["detected_at"] = r["detected_at"].isoformat()
    return jsonify(rows)


@app.route("/api/stats/summary")
def summary():
    sql = f"""
        SELECT
          COUNT(*) AS total_anomalies,
          COUNTIF(severity = 'CRITICAL') AS critical,
          COUNTIF(severity = 'HIGH') AS high,
          COUNTIF(severity = 'MEDIUM') AS medium,
          COUNT(DISTINCT sensor_id) AS sensors_affected
        FROM `{PROJECT_ID}.{DATASET_ID}.anomalies`
        WHERE detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    """
    rows = run_query(sql)
    return jsonify(rows[0] if rows else {})


@app.route("/api/stats/by_sensor")
def by_sensor():
    sql = f"""
        SELECT sensor_id, COUNT(*) AS anomaly_count,
               MAX(detected_at) AS last_seen
        FROM `{PROJECT_ID}.{DATASET_ID}.anomalies`
        WHERE detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        GROUP BY sensor_id
        ORDER BY anomaly_count DESC
    """
    rows = run_query(sql)
    for r in rows:
        if hasattr(r.get("last_seen"), "isoformat"):
            r["last_seen"] = r["last_seen"].isoformat()
    return jsonify(rows)


@app.route("/api/readings/latest")
def latest_readings():
    sql = f"""
        SELECT sensor_id, ingested_at, temperature, humidity, wind_speed, pressure
        FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY sensor_id ORDER BY ingested_at DESC) rn
          FROM `{PROJECT_ID}.{DATASET_ID}.sensor_readings`
        )
        WHERE rn = 1
    """
    rows = run_query(sql)
    for r in rows:
        if hasattr(r.get("ingested_at"), "isoformat"):
            r["ingested_at"] = r["ingested_at"].isoformat()
    return jsonify(rows)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
