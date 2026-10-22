# Gossip

Gossip is a Python pipeline that turns municipal council protocols from
[SessionNet](https://sessionnet.owl-it.de/) into local-news articles, images,
and Instagram assets. It runs as a containerized FastAPI application with
PostgreSQL and an in-process APScheduler.

## What it does

1. **Fetch** — reads the SessionNet protocol list, downloads new PDFs, and
   extracts their text with PyMuPDF.
2. **Deduplicate** — compares new protocols against the previous 90 days using
   a 95% text-similarity threshold.
3. **Generate articles** — sends protocol text to Google Gemini and validates
   the response against a structured article schema.
4. **Generate images** — creates an image prompt, verifies/rewrites it for a
   realistic style, and generates the image with Gemini's image model.
5. **Render Instagram assets** — generates captions and 4:5 images with the
   headline, logo, and protocol tag overlaid.
6. **Persist and serve** — stores protocols/articles in PostgreSQL, writes
   images and HTML to the articles directory, and exposes the results through
   a REST API.

The workflow is triggered by APScheduler and can also be started manually
through the API.

## Architecture

```
SessionNet ──▶ Protocol fetcher ──▶ PostgreSQL
                                      │
                                      ▼
                              Article generator ──▶ Gemini
                                      │
                                      ▼
                              Image generator ─────▶ Gemini image model
                                      │
                                      ▼
                              Instagram renderer ──▶ articles/ + DB
                                      │
                                      ▼
                                   FastAPI
```

The FastAPI process starts the scheduler during application startup. There is
currently no separate worker process, so run a single application replica.

## Project structure

```
app/
├── api/routes.py              REST endpoints and manual pipeline triggers
├── core/
│   ├── config.py              Environment-backed settings
│   ├── models.py              Pydantic response models
│   ├── prompts.py             Gemini prompts
│   └── tags.py                Protocol-to-tag mapping
├── database.py                Async SQLAlchemy engine/session
├── main.py                    FastAPI entry point and lifespan
├── models.py                  SQLAlchemy models (Protocol, Article)
├── scheduler.py               APScheduler cron jobs
├── services/
│   ├── protocol_fetcher.py    SessionNet scraping and PDF ingestion
│   ├── protocol_processor.py  Orchestrates article/image/Instagram creation
│   ├── article_generator.py   Gemini article generation
│   ├── image_generator.py     Gemini image generation
│   ├── caption_generator.py   Instagram captions
│   ├── insta_generator.py     Instagram image rendering
│   ├── insta_job.py           Batch Instagram generation
│   └── duplicate_detector.py  Protocol similarity check
├── utils/                     Folder and SessionNet helpers
└── res/                       Logo and fonts used by the renderer

tests/
├── unit/                      Fast unit tests
├── integration/               Integration test package
└── manual/                    Real-API tests (not run by default)

docs/agents/                   Agent workflow configuration (Pocock skills)
local-testing/                 Local compose file and database dump
```

`src/`, `alembic/`, and a root `main.py` no longer exist. Database tables are
created with SQLAlchemy `create_all()` on startup; migrations have not been
introduced yet.

## Quick start (Docker)

Prerequisites: Docker, Docker Compose, and the external networks used by
`docker-compose.yaml`.

```bash
cp .env.example .env
# Edit .env: at minimum set GOOGLE_API_KEY and a real DB_PASSWORD.

docker network create traefik-proxy   # skip if it already exists
docker network create gossip-net      # skip if it already exists
docker compose up -d --build
```

The application listens on port 8000 inside the Compose network and is routed
by Traefik at the configured host. The host paths for article and log output
are set in `docker-compose.yaml`; adjust them for your deployment.

## Local development

Python 3.12 is required (the Docker image uses `python:3.12-slim`).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# For a local Postgres container, set DB_HOST=localhost in .env.

docker run -d --name gossip-postgres \
  -e POSTGRES_DB=gossip \
  -e POSTGRES_USER=gossip_user \
  -e POSTGRES_PASSWORD=secure_password \
  -p 5432:5432 postgres:16

uvicorn app.main:app --reload
```

The API is then available at `http://127.0.0.1:8000`, with Swagger UI at
`/docs`.

## Configuration

Configuration is read from `.env` (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection |
| `DATABASE_URL` | Optional full SQLAlchemy URL; overrides the `DB_*` values |
| `GOOGLE_API_KEY` | Google GenAI API key |
| `SESSIONNET_BASE_URL` | SessionNet base URL |
| `TRAEFIK_HOST` | Public hostname used by the deployment |
| `LOG_LEVEL` | Python log level (`INFO` by default) |
| `ARTICLES_DIR` | Output directory for articles and generated images |
| `LOGS_DIR` | Log output directory |

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Application metadata |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/protocols` | List protocols (`skip`, `limit`, `processed`) |
| `GET` | `/api/protocols/{id}` | Protocol detail, including extracted PDF text |
| `GET` | `/api/protocols/{id}/articles` | Articles for a protocol |
| `GET` | `/api/stats` | Protocol/article counts |
| `POST` | `/api/pipeline/fetch` | Fetch new protocols now |
| `POST` | `/api/pipeline/process` | Process unprocessed protocols now |
| `POST` | `/api/pipeline/run` | Fetch and process in one call |
| `POST` | `/api/pipeline/generate-insta` | Generate Instagram assets (optional `protocol_id`) |
| `GET` | `/api/pipeline/status` | Pipeline backlog and counts |
| `GET` | `/docs` | Swagger UI |

The pipeline endpoints call the same jobs as the scheduler and can take a long
time when Gemini is involved. They are currently unauthenticated; restrict
access at the reverse proxy or add authentication before exposing the service
publicly.

## Scheduled jobs

| Job | Schedule (Europe/Berlin) | Description |
| --- | --- | --- |
| `fetch_protocols` | 10:00 and 17:00 | Fetch new protocols from SessionNet |
| `process_protocols` | 10:30 and 17:30 | Process unprocessed protocols |

Because the scheduler runs inside the web process, do not scale the `app`
service to multiple replicas without moving the scheduler to a dedicated
worker first.

## Tests and linting

```bash
pytest -m "not manual"   # standard test suite
pytest -m manual         # real Gemini calls; requires GOOGLE_API_KEY
ruff check .
```

`pytest` runs the unit suite by default. Manual tests are marked and should
only be run when you intend to spend API credits.

## Operational notes

- The application writes generated articles and images to `ARTICLES_DIR` and
  logs to `LOGS_DIR`. Both are bind-mounted in `docker-compose.yaml`.
- PostgreSQL is only reachable on the internal Compose network.
- The Compose router uses the `web` entrypoint; TLS is expected to terminate
  at the Cloudflare/Traefik edge. Verify the entrypoint against your actual
  Traefik configuration before changing it.
- The API currently has no built-in authentication, rate limiting, or request
  size limits.

## Known limitations / next steps

- Add Alembic migrations instead of `create_all()`.
- Move the scheduler and long-running pipeline jobs into a dedicated worker.
- Add authentication and rate limiting for the API and pipeline triggers.
- Store article content as structured blocks instead of an HTML string.
- Replace the O(n²) full-text duplicate check with a hash or MinHash index.
- Add structured logging and job-level locking to prevent overlapping runs.
