"""
Data Ingestion Service
Fetches real-time data from Open-Meteo (free, no API key needed)
and streams it to BigQuery for anomaly detection.
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ID   = os.environ["GCP_PROJECT_ID"]
DATASET_ID   = os.environ.get("BQ_DATASET", "anomaly_detection")
TABLE_ID     = os.environ.get("BQ_TABLE",   "sensor_readings")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))

# Open-Meteo – free, no key required
# We simulate multiple "sensors" by pulling several weather stations
STATIONS = [
    {"id": "NYC",    "lat": 40.71,  "lon": -74.01},
    {"id": "LONDON", "lat": 51.51,  "lon": -0.13},
    {"id": "TOKYO",  "lat": 35.68,  "lon": 139.69},
    {"id": "SYDNEY", "lat": -33.87, "lon": 151.21},
    {"id": "DUBAI",  "lat": 25.20,  "lon": 55.27},
]

METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,surface_pressure"
    "&wind_speed_unit=ms"
)

bq_client = bigquery.Client(project=PROJECT_ID)
TABLE_REF  = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"


def ensure_table():
    """Create BQ dataset + table if they don't exist."""
    try:
        bq_client.get_dataset(DATASET_ID)
    except Exception:
        bq_client.create_dataset(bigquery.Dataset(f"{PROJECT_ID}.{DATASET_ID}"))
        log.info("Created dataset %s", DATASET_ID)

    schema = [
        bigquery.SchemaField("ingested_at",  "TIMESTAMP"),
        bigquery.SchemaField("sensor_id",    "STRING"),
        bigquery.SchemaField("latitude",     "FLOAT"),
        bigquery.SchemaField("longitude",    "FLOAT"),
        bigquery.SchemaField("temperature",  "FLOAT"),
        bigquery.SchemaField("humidity",     "FLOAT"),
        bigquery.SchemaField("wind_speed",   "FLOAT"),
        bigquery.SchemaField("pressure",     "FLOAT"),
    ]
    table = bigquery.Table(TABLE_REF, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(field="ingested_at")
    try:
        bq_client.create_table(table)
        log.info("Created table %s", TABLE_REF)
    except Exception:
        pass  # already exists


def fetch_station(station: dict) -> dict | None:
    url = METEO_URL.format(lat=station["lat"], lon=station["lon"])
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        cur = r.json().get("current", {})
        return {
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "sensor_id":   station["id"],
            "latitude":    station["lat"],
            "longitude":   station["lon"],
            "temperature": cur.get("temperature_2m"),
            "humidity":    cur.get("relative_humidity_2m"),
            "wind_speed":  cur.get("wind_speed_10m"),
            "pressure":    cur.get("surface_pressure"),
        }
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", station["id"], exc)
        return None


def ingest():
    rows = [r for s in STATIONS if (r := fetch_station(s))]
    if not rows:
        log.warning("No rows fetched this round")
        return

    errors = bq_client.insert_rows_json(TABLE_REF, rows)
    if errors:
        log.error("BQ insert errors: %s", errors)
    else:
        log.info("Inserted %d rows → %s", len(rows), TABLE_REF)


def main():
    ensure_table()
    log.info("Ingestion service started – polling every %ds", POLL_SECONDS)
    while True:
        ingest()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
