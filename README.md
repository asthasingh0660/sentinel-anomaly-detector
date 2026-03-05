# 🛡️ SENTINEL — Real-time AI Anomaly Detection on GCP

A production-grade data engineering + AI project that runs **entirely within GCP's free tier**.

## Architecture

```
Open-Meteo API (free, no key)
        │
        ▼
┌─────────────────────┐       every 60s
│  sentinel-ingestion  │──────────────────→ BigQuery
│  (Cloud Run)         │                   sensor_readings table
└─────────────────────┘

Cloud Scheduler (every 5 min)
        │
        ▼
┌─────────────────────┐   reads BQ   ┌──────────────┐
│  sentinel-detector  │──────────────│  BigQuery    │
│  (Cloud Run)         │              │  z-score     │
│  + Claude AI         │──────────────│  anomalies   │
└─────────────────────┘  writes BQ   └──────────────┘
                                              │
                                              ▼
                                  ┌─────────────────────┐
                                  │  sentinel-dashboard  │
                                  │  (Cloud Run)         │
                                  │  Live HTML UI        │
                                  └─────────────────────┘
```

## Services

| Service | What it does | Free tier |
|---|---|---|
| **sentinel-ingestion** | Polls 5 weather stations every 60s, writes to BigQuery | Cloud Run: 2M req/month free |
| **sentinel-detector** | Triggered by Scheduler, runs z-score anomaly detection + Claude AI explanations | Cloud Run + Scheduler: free |
| **sentinel-dashboard** | Flask + HTML dashboard showing live anomalies | Cloud Run: free |
| **BigQuery** | Stores readings & anomalies | 10GB storage + 1TB queries/month free |

## Prerequisites

```bash
# Install Google Cloud CLI
# https://cloud.google.com/sdk/docs/install

gcloud --version        # verify install
docker --version        # need Docker too

# Login
gcloud auth login
gcloud auth application-default login
```

## Setup (one-time, ~10 minutes)

### 1. Create a GCP Project
```bash
# In GCP Console: https://console.cloud.google.com
# Click "New Project" → give it a name → note the Project ID
```

### 2. Edit deploy.sh
Open `deploy.sh` and fill in:
```bash
PROJECT_ID="your-actual-project-id"
ANTHROPIC_API_KEY="sk-ant-..."    # get from console.anthropic.com
```

Also edit the same values in `stop.sh` and `start.sh`.

### 3. Deploy
```bash
chmod +x deploy.sh stop.sh start.sh
bash deploy.sh
```

This will:
- Enable GCP APIs
- Build and push 3 Docker images
- Deploy 3 Cloud Run services
- Set up Cloud Scheduler to run detection every 5 min

### 4. Wait ~5 minutes for first data, then open the dashboard URL printed at the end!

---

## 🛑 Stopping to Save Credits

```bash
bash stop.sh
```

This **pauses the scheduler** and **scales Cloud Run to 0**.
- No compute charges while stopped
- Your BigQuery data is preserved
- BigQuery free tier = 10GB storage + 1TB queries/month (you'll use <1MB)

## ▶ Restarting

```bash
bash start.sh
```

---

## How Anomaly Detection Works

1. **Ingestion**: Fetches `temperature`, `humidity`, `wind_speed`, `pressure` from 5 cities (NYC, London, Tokyo, Sydney, Dubai) every minute via the Open-Meteo free API.

2. **Statistical z-score**: For each sensor × metric pair, compute:
   ```
   z = (latest_value - mean) / std_dev
   ```
   over the last 24 hours. If `|z| ≥ 2.5`, it's an anomaly.

3. **AI Explanation**: Claude (claude-sonnet) writes a 2-3 sentence plain-English explanation of why the anomaly occurred and whether it needs attention.

4. **Dashboard**: Auto-refreshes every 30s showing anomaly feed, sensor activity bars, and live readings table.

---

## Estimated GCP Costs

| Resource | Free Tier | Projected Usage |
|---|---|---|
| Cloud Run requests | 2M/month free | ~9,000/month (5min intervals) |
| Cloud Run compute | 360,000 vCPU-sec/month free | ~500 vCPU-sec/month |
| BigQuery storage | 10 GB free | < 10 MB |
| BigQuery queries | 1 TB/month free | < 100 MB |
| Artifact Registry | 0.5 GB free | ~300 MB |
| Cloud Scheduler | 3 jobs free | 1 job used |

**Total GCP cost: $0** ✅

Anthropic API (Claude): Roughly **$0.01–0.05/day** depending on anomaly frequency (each explanation is ~200 tokens).

---

## Project Structure

```
anomaly-detector/
├── ingestion/
│   ├── main.py           # polls Open-Meteo → BigQuery
│   ├── requirements.txt
│   └── Dockerfile
├── detector/
│   ├── main.py           # z-score + Claude AI → anomalies table
│   ├── requirements.txt
│   └── Dockerfile
├── dashboard/
│   ├── main.py           # Flask API + static file server
│   ├── requirements.txt
│   ├── Dockerfile
│   └── static/
│       └── index.html    # live anomaly dashboard UI
├── deploy.sh             # full GCP deploy
├── stop.sh               # pause everything (save credits)
├── start.sh              # resume everything
└── README.md
```

## Customization Ideas

- **Add more sensors**: Edit `STATIONS` list in `ingestion/main.py`
- **Change data source**: Swap Open-Meteo for any free REST API (CoinGecko, Open AQ, etc.)
- **Tune sensitivity**: Change `Z_THRESHOLD` env var (lower = more sensitive)
- **Add alerts**: Send anomaly summaries to Slack/email using Claude's API in the detector
- **Export to GCS**: Save anomaly reports as JSON files to Cloud Storage

---

## Useful Commands

```bash
# View logs for any service
gcloud run services logs read sentinel-detector --region=us-central1

# Manually trigger detection (useful for testing)
curl -X POST $(gcloud run services describe sentinel-detector \
  --region=us-central1 --format="value(status.url)")/detect \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Check BigQuery tables
bq query --use_legacy_sql=false \
  'SELECT * FROM anomaly_detection.sensor_readings LIMIT 5'

# Delete everything (if done with project)
bash destroy.sh
```
