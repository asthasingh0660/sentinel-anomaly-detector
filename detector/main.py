"""
Anomaly Detection Service (Cloud Run – HTTP)
- Reads last N hours from BigQuery
- Computes z-score per sensor per metric
- Flags anomalies (|z| > threshold)
- Calls Claude AI to explain each anomaly in plain English
- Writes results back to BigQuery anomalies table
- Exposes /detect endpoint so Cloud Scheduler can trigger it
"""

import os
import json
import logging
import anthropic
from datetime import datetime, timezone
from flask import Flask, jsonify
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

PROJECT_ID      = os.environ["GCP_PROJECT_ID"]
DATASET_ID      = os.environ.get("BQ_DATASET",    "anomaly_detection")
TABLE_ID        = os.environ.get("BQ_TABLE",      "sensor_readings")
ANOMALY_TABLE   = os.environ.get("ANOMALY_TABLE", "anomalies")
Z_THRESHOLD     = float(os.environ.get("Z_THRESHOLD", "2.5"))
LOOKBACK_HOURS  = int(os.environ.get("LOOKBACK_HOURS", "24"))

bq = bigquery.Client(project=PROJECT_ID)
ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

ANOMALY_TABLE_REF = f"{PROJECT_ID}.{DATASET_ID}.{ANOMALY_TABLE}"

METRICS = ["temperature", "humidity", "wind_speed", "pressure"]


def ensure_anomaly_table():
    schema = [
        bigquery.SchemaField("detected_at",   "TIMESTAMP"),
        bigquery.SchemaField("sensor_id",     "STRING"),
        bigquery.SchemaField("metric",        "STRING"),
        bigquery.SchemaField("value",         "FLOAT"),
        bigquery.SchemaField("mean",          "FLOAT"),
        bigquery.SchemaField("std_dev",       "FLOAT"),
        bigquery.SchemaField("z_score",       "FLOAT"),
        bigquery.SchemaField("severity",      "STRING"),
        bigquery.SchemaField("ai_explanation","STRING"),
    ]
    table = bigquery.Table(ANOMALY_TABLE_REF, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(field="detected_at")
    try:
        bq.create_table(table)
        log.info("Created anomaly table")
    except Exception:
        pass


def fetch_recent_readings() -> list[dict]:
    query = f"""
        SELECT sensor_id, ingested_at, temperature, humidity, wind_speed, pressure
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE ingested_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {LOOKBACK_HOURS} HOUR)
        ORDER BY sensor_id, ingested_at
    """
    rows = list(bq.query(query).result())
    return [dict(r) for r in rows]


def compute_stats(readings: list[dict], metric: str) -> dict:
    """Returns {sensor_id: {mean, std, latest_value}} for a given metric."""
    from collections import defaultdict
    import statistics

    by_sensor = defaultdict(list)
    for r in readings:
        v = r.get(metric)
        if v is not None:
            by_sensor[r["sensor_id"]].append((r["ingested_at"], float(v)))

    stats = {}
    for sensor, pairs in by_sensor.items():
        values = [v for _, v in pairs]
        if len(values) < 3:
            continue
        mean = statistics.mean(values)
        std  = statistics.stdev(values) or 0.0001
        latest_ts, latest_val = max(pairs, key=lambda x: x[0])
        stats[sensor] = {
            "mean": mean, "std": std,
            "latest": latest_val, "latest_ts": latest_ts
        }
    return stats


def severity(z: float) -> str:
    az = abs(z)
    if az > 4:   return "CRITICAL"
    if az > 3:   return "HIGH"
    return "MEDIUM"


def explain_anomaly(sensor_id: str, metric: str, value: float,
                    mean: float, std: float, z: float) -> str:
    prompt = (
        f"You are a data engineer monitoring sensor data. "
        f"Sensor '{sensor_id}' reported {metric} = {value:.2f} "
        f"(mean={mean:.2f}, std={std:.2f}, z-score={z:.2f}). "
        f"In 2-3 sentences: explain why this is anomalous, what might cause it, "
        f"and whether it needs urgent attention. Be concise and specific."
    )
    msg = ai.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


@app.route("/detect", methods=["POST", "GET"])
def detect():
    ensure_anomaly_table()
    readings = fetch_recent_readings()
    if not readings:
        return jsonify({"status": "ok", "anomalies": 0, "message": "No data yet"})

    found = []
    for metric in METRICS:
        stats = compute_stats(readings, metric)
        for sensor_id, s in stats.items():
            z = (s["latest"] - s["mean"]) / s["std"]
            if abs(z) >= Z_THRESHOLD:
                explanation = explain_anomaly(
                    sensor_id, metric, s["latest"], s["mean"], s["std"], z
                )
                found.append({
                    "detected_at":    datetime.now(timezone.utc).isoformat(),
                    "sensor_id":      sensor_id,
                    "metric":         metric,
                    "value":          s["latest"],
                    "mean":           round(s["mean"], 4),
                    "std_dev":        round(s["std"], 4),
                    "z_score":        round(z, 4),
                    "severity":       severity(z),
                    "ai_explanation": explanation,
                })
                log.info("Anomaly: %s / %s z=%.2f", sensor_id, metric, z)

    if found:
        errors = bq.insert_rows_json(ANOMALY_TABLE_REF, found)
        if errors:
            log.error("BQ errors: %s", errors)

    return jsonify({
        "status":    "ok",
        "anomalies": len(found),
        "detected":  found
    })


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
