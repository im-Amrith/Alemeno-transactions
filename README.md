# AI-Powered Transaction Processing Pipeline

A backend service that ingests a dirty CSV of financial transactions, processes it
asynchronously through a job queue, uses an LLM (Groq) to classify transactions and
generate a narrative summary, and exposes results via a polling REST API.

## Stack

- **API**: FastAPI
- **Database**: PostgreSQL (via SQLAlchemy + Alembic migrations)
- **Job queue**: Celery + Redis
- **LLM**: Groq (`llama-3.1-8b-instant` by default — free tier, fast)
- **Containerisation**: Docker Compose

## Architecture

```
Client --> FastAPI (upload/status/results) --> PostgreSQL (Job, Transaction, JobSummary)
              |
              v
           Redis (Celery broker)
              |
              v
       Celery worker: clean -> detect anomalies -> classify (Groq, batched) -> narrative (Groq) -> persist
```

Request lifecycle for `POST /jobs/upload`:
1. CSV is validated and saved to a shared volume.
2. A `Job` row is created with `status=pending` and committed to Postgres.
3. A Celery task is enqueued on Redis; the `job_id` is returned immediately (API never blocks on processing).
4. The worker picks up the task, sets `status=processing`, cleans the data, flags anomalies,
   classifies uncategorised rows in batches of ~18 via Groq, generates a single narrative-summary
   call, persists everything, and sets `status=completed` (or `failed` with `error_message`).

## Setup

1. Copy the env file and add your Groq API key (free tier key from [console.groq.com](https://console.groq.com)):
   ```bash
   cp .env.example .env
   # edit .env and set GROQ_API_KEY=...
   ```

2. Start everything with a single command:
   ```bash
   docker compose up --build
   ```
   This brings up Postgres, Redis, runs Alembic migrations, then starts the API (port 8000) and the Celery worker. No manual setup steps required.

3. Confirm the API is up:
   ```bash
   curl http://localhost:8000/health
   ```

## API Reference & Example Requests

### Upload a CSV for processing
```bash
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@transactions.csv"
```
Response:
```json
{ "job_id": "9c2e1e2a-....", "status": "pending" }
```

### Poll job status
```bash
curl http://localhost:8000/jobs/9c2e1e2a-..../status
```
Response (while processing):
```json
{ "job_id": "...", "status": "processing", "row_count_raw": 95, "row_count_clean": null }
```
Response (when completed):
```json
{
  "job_id": "...",
  "status": "completed",
  "row_count_raw": 95,
  "row_count_clean": 85,
  "summary": {
    "total_spend_inr": 1234567.89,
    "total_spend_usd": 4321.0,
    "top_merchants": ["Amazon", "Swiggy", "Flipkart"],
    "anomaly_count": 5,
    "risk_level": "medium"
  }
}
```

### Get full results
```bash
curl http://localhost:8000/jobs/9c2e1e2a-..../results
```
Returns the cleaned transaction list, flagged anomalies, per-category spend breakdown, and
the LLM-generated narrative summary.

### List all jobs (with optional status filter)
```bash
curl http://localhost:8000/jobs
curl "http://localhost:8000/jobs?status=completed"
```

## Processing pipeline details

- **Cleaning**: dates normalised to ISO 8601 (handles `DD-MM-YYYY`, `YYYY/MM/DD`, and plain ISO
  inputs found in the source data); `$` stripped from amounts; `currency`/`status` uppercased;
  blank `category` filled with `Uncategorised`; exact duplicate rows dropped.
- **Anomaly detection**: flags amounts >3x the account's median, and USD-denominated transactions
  on domestic-only merchants (Swiggy, Ola, IRCTC).
- **LLM classification**: only rows missing a category are sent to Groq, in batches of ~18
  (configurable via `CLASSIFICATION_BATCH_SIZE`) — never one call per row.
- **LLM narrative summary**: a single Groq call per job, given precomputed ground-truth stats
  (totals, top merchants, anomaly count) so the LLM only narrates rather than doing arithmetic.
- **Retry logic**: both LLM call types retry up to 3 times with exponential backoff
  (`tenacity`). If a classification batch exhausts retries, those rows are persisted with
  `llm_failed=true` and the job still completes — a failed batch never fails the whole job.

## Running tests

Cleaning and anomaly-detection logic is pure/unit-testable without Docker:
```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Project structure

```
app/            FastAPI app, config, DB models/schemas, Celery app definition
worker/         Celery tasks, cleaning logic, Groq LLM wrapper
alembic/        DB migrations
tests/          Unit tests for cleaning/anomaly logic
docker-compose.yml
Dockerfile
```
