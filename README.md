# Gossip

Gossip is a Python service that fetches municipal council protocols from
[SessionNet](https://sessionnet.owl-it.de/), deduplicates them, and stores them
in PostgreSQL. It runs as a containerized FastAPI application with an
in-process APScheduler.

The stateless post pipeline is being built in stages. The editorial planning
stage, the Summary content path, the Summary visual output and the topic
content path are implemented: a protocol becomes a persisted Redaktionsplan
plus draft Summary and topic posts with deterministic source excerpts. The
Summary post gets a validated writer draft, a hard fact-check gate with one
repair, deterministic Summary cards, a composed caption, Alt-Texte, an AI cover
image with a brand fallback, and the blue 9:16 story PNGs plus one caption file
in the protocol folder. Each topic post gets a validated article (H1, two to
six H2 sections and paragraphs), the same hard fact-check gate, four to seven
deterministic content slides, a composed caption and Alt-Texte. Topic visuals,
retry/reprocess endpoints, and scheduler wiring are still to come. The legacy
one-call article, caption, image, and Instagram pipeline has been removed;
legacy articles remain readable through the API.

## What it does

1. **Fetch** — reads the SessionNet protocol list, downloads new PDFs, and
   extracts their text with PyMuPDF.
2. **Deduplicate** — compares new protocols against the previous 90 days using
   a 95% text-similarity threshold.
3. **Persist and serve** — stores protocols in PostgreSQL, keeps legacy
   articles readable, and exposes protocols, stats, and pipeline status through
   a REST API.
4. **Plan** — the stateless Redaktionsplaner turns a protocol into a plan with
   two to six Summary briefs and zero to five topic briefs, including exact
   source anchors. Deterministic steps resolve the official Organ and retrieve
   only the referenced protocol excerpts. The result is persisted as an
   `editorial_plans` row and draft posts.
5. **Summarise** — the Summary-Writer turns the Summary briefs and excerpts
   into a cover title and two to six Summary-Punkte. The Faktenprüfung is a
   hard gate with one repair attempt, and the 9:16 Summary cards are composed
   deterministically at one post-wide body size. The Summary post also gets a
   composed caption and deterministic Alt-Texte.
6. **Visualise** — a stateless visual-prompt call writes the cover prompt from
   the Summary draft only. Image generation requests a 9:16 image through the
   LLM port, center-fits it to exactly 1080×1920, and substitutes the
   deterministic blue brand fallback if the provider or payload fails. The
   renderer writes the cover and two to six cards as
   `summary-<date>-story-<frame>.png` plus exactly one
   `caption-summary-summary.txt` into the protocol folder. Alt-Texte stay in
   PostgreSQL and the API; no JSON, Markdown, prompt, or manifest files are
   written. Only after the whole story and caption are written does the
   Summary post become `ready`.
7. **Write topics** — for each planned Themenbrief, the Themen-Writer sees only
   that brief and its excerpts and writes an H1 plus two to six H2 sections
   with paragraphs under a hard 3,000-character budget. The same Fact-Check
   gate applies, and the 4:5 content slides are composed deterministically:
   every H2 starts a new slide, overflow continues with the short chapter label
   at one post-wide body size, and the article text is never reworded or
   truncated. Topics also get a caption and Alt-Texte and stay `draft` until
   the topic visual ticket runs.

The fetch workflow is triggered by APScheduler and can also be started manually
through the API. The planning, Summary content and visual, and topic content
stages are callable through `PostPipeline.run`; scheduler wiring arrives with
the later pipeline tickets.
The processing schedule slot is reserved but currently a no-op.

## Architecture

```
SessionNet ──▶ Protocol fetcher ──▶ PostgreSQL ──▶ FastAPI
                     │
                     └──────────▶ Duplicate detector
```

The FastAPI process starts the scheduler during application startup. There is
currently no separate worker process, so run a single application replica.

## Project structure

```
app/
├── api/routes.py              REST endpoints (fetch, stats, status, posts)
├── core/
│   ├── config.py              Environment-backed settings
│   ├── post_models.py         Strict Pydantic models for pipeline I/O
│   └── post_prompts.py        Pure prompt builders per LLM role
├── database.py                Async SQLAlchemy engine/session
├── main.py                    FastAPI entry point and lifespan
├── models.py                  SQLAlchemy models (protocols, articles, posts, slides, assets, plans)
├── scheduler.py               APScheduler cron jobs and post-pipeline seam
├── services/
│   ├── protocol_fetcher.py    SessionNet scraping and PDF ingestion
│   ├── duplicate_detector.py  Protocol similarity check
│   ├── openrouter_client.py   Synchronous OpenRouter transport
│   ├── llm_client.py          Stateless LLM port and OpenRouter adapter
│   ├── editorial_planner.py   Redaktionsplaner role
│   ├── summary_writer.py      Summary-Writer role with one validation retry
│   ├── topic_writer.py        Themen-Writer role with one validation retry
│   ├── fact_checker.py        Shared fact-check + one-repair hard gate
│   ├── slide_composer.py      Deterministic Summary cards and topic slides
│   ├── caption_writer.py      Caption body role and deterministic composition
│   ├── visual_prompts.py      Stateless visual-prompt role for covers/artwork
│   ├── image_generation.py    Image decode, deterministic fit, brand fallbacks
│   ├── post_renderer.py       Deterministic Summary story renderer
│   ├── render_common.py       Shared colors, logo plate, scrim, badge, folders
│   ├── text_layout.py         Shared font loading, wrapping and fit primitives
│   ├── organs.py              Finite Organ seed and deterministic resolver
│   ├── protocol_excerpts.py   Deterministic source-anchor retrieval
│   └── post_pipeline.py       Planning, content and Summary visual orchestrator
├── utils/                     Folder and SessionNet helpers
└── res/                       Logo and runtime fonts for the renderer

tests/
├── unit/                      Fast tests with a fake LLM client
├── integration/               Real-PostgreSQL tests for schema, API and pipeline
├── support/                   Reusable FakeLLMClient test seam
└── manual/                    Real-API tests (not run by default)

docs/agents/                   Agent workflow configuration (Pocock skills)
local-testing/                 Local compose file and database dump
```

The renderer requires three committed runtime assets in `app/res/`:
`logo-gossip.png` (colored RGBA logo, placed on the white plate),
`Oswald-var.ttf` (titles, headings, numbers, kickers) and `Inter-var.ttf`
(body copy, badges, page labels). A missing asset is a hard render failure; it
never falls back to another font or logo.

`src/`, `alembic/`, and a root `main.py` no longer exist. Database tables are
created with SQLAlchemy `create_all()` on startup; migrations have not been
introduced yet.

## Quick start (Docker)

Prerequisites: Docker, Docker Compose, and the external networks used by
`docker-compose.yaml`.

```bash
cp .env.example .env
# Edit .env: at minimum set OPENROUTER_API_KEY and a real DB_PASSWORD.

docker network create traefik-proxy   # skip if it already exists
docker network create gossip-net      # skip if it already exists
docker compose up -d --build
```

The application listens on port 8000 inside the Compose network and is routed
by Traefik at the configured host. The host directory for generated images and
log output is set with `GOSSIP_DATA_DIR` in `.env`; the default is `./data`.
For the existing deployment, set it to `/home/openclaw/data/gossip`.

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
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENROUTER_TEXT_MODEL` | Text model (default: `deepseek/deepseek-v4.1-flash-1017`) |
| `OPENROUTER_IMAGE_MODEL` | Image model (default: `google/gemini-3.1-flash-image`) |
| `OPENROUTER_REASONING_EFFORT` | Reasoning effort for text calls (default: `max`) |
| `SESSIONNET_BASE_URL` | SessionNet base URL |
| `TRAEFIK_HOST` | Public hostname used by the deployment |
| `LOG_LEVEL` | Python log level (`INFO` by default) |
| `GOSSIP_DATA_DIR` | Host directory for generated images and logs (Compose only; default `./data`) |
| `ARTICLES_DIR` | Output directory for generated images (container path) |
| `LOGS_DIR` | Log output directory (container path) |
| `TEST_DATABASE_URL` | PostgreSQL database for integration tests; unset skips them |

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Application metadata |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/protocols` | List protocols (`skip`, `limit`, `processed`) |
| `GET` | `/api/protocols/{id}` | Protocol detail, including extracted PDF text |
| `GET` | `/api/protocols/{id}/articles` | Legacy articles for a protocol |
| `GET` | `/api/protocols/{id}/posts` | Summary and topic posts for a protocol, ordered by `post_index` |
| `GET` | `/api/posts/{id}` | One post with ordered slides and assets |
| `GET` | `/api/stats` | Protocol/article counts and `post_counts` |
| `POST` | `/api/pipeline/fetch` | Fetch new protocols now |
| `GET` | `/api/pipeline/status` | Pipeline backlog, article counts, and `post_counts` |
| `GET` | `/docs` | Swagger UI |

The fetch endpoint calls the same job as the scheduler. Post generation
endpoints will return with the stateless post pipeline; the old process, run,
and generate-insta triggers are gone.

Planned Beiträge are already persisted and readable. The planning stage stores
the Redaktionsplan and creates the summary post (`slug="summary"`,
`post_index=0`) and zero to five topic posts as `status="draft"`. The Summary
content path then replaces the summary's `content_json` with the validated
draft plus source excerpts and fills `content_markdown`, `slide_plan_json`,
`caption`, `alt_text_json`, `fact_check_json` and the one-based cover/card
`post_slides`. Each topic post gets the same persisted fields from its own
writer, fact-check, composition and caption calls, with one-based
cover/heading/continuation `post_slides`. The Summary visual stage writes the
cover prompt and asset row, generates or falls back for the cover art, renders
all 1080×1920 frames in memory, and writes the PNGs plus the caption file
before flipping the Summary to `ready`. Rerunning a protocol reuses a cached
Summary draft and composed slides and resumes at visuals instead of calling the
Summary writer again; a `ready` Summary is skipped entirely. Topic posts stay
`draft` until the topic visual ticket renders them.
An unknown protocol title marks all planned posts `failed` at `organ`, and a
missing source anchor marks only the affected Beitrag `failed` at
`source_retrieval`. Summary and topic branches are independent: a Summary
failure at `writer`, `fact_check`, `repair`, `caption`, `slide_composer`,
`visual_prompts`, `image_generation` or `render` does not touch the topic
drafts, and a failed topic does not block the Summary or the other topics.
Failed posts are not retried automatically on the next run.

### Summary output files

For a protocol titled `Gemeinderat` from 2024-01-15, the renderer writes into
`<ARTICLES_DIR>/240115_gemeinderat/`:

```
summary-2024-01-15-story-01.png   # cover
summary-2024-01-15-story-02.png   # first card
summary-2024-01-15-story-03.png   # second card
caption-summary-summary.txt
```

The folder is reused idempotently. A Summary story has three to seven frames
(cover plus two to six cards) and exactly one caption file whose content is the
stored `post.caption`, starting with `Illustration: KI-generiert.` and carrying
the source/date plus the SessionNet link or the manual-link hint. Image
failures produce the blue brand fallback and the post still becomes `ready`;
authentication errors stop the job immediately. Text overflow, a missing
font/logo, or a caption/render write failure marks the Summary `failed` at
`render` and writes no partial story.

### Post read API

`GET /api/protocols/{id}/posts` returns a compact list ordered by `post_index`
and responds with `404` for an unknown protocol:

```json
[
  {
    "id": 1,
    "protocol_id": 7,
    "post_type": "summary",
    "slug": "summary",
    "post_index": 0,
    "title": "Sitzung kompakt",
    "status": "ready",
    "failed_step": null,
    "caption": "Illustration: KI-generiert. ...",
    "slide_count": 3,
    "created_at": "2024-01-15T10:00:00",
    "updated_at": "2024-01-15T11:00:00"
  }
]
```

`GET /api/posts/{id}` returns the full post and responds with `404` for an
unknown post. It adds the content, fact-check and generator fields, plus the
ordered `slides` and `assets`:

```json
{
  "id": 1,
  "protocol_id": 7,
  "post_type": "topic",
  "slug": "haushalt",
  "post_index": 1,
  "title": "Haushalt",
  "content_json": {"sections": []},
  "content_markdown": "## Haushalt\n\n...",
  "slide_plan_json": {"slides": []},
  "caption": "Illustration: KI-generiert. ...",
  "alt_text_json": ["..."],
  "fact_check_json": {"passed": true, "issues": [], "repaired": false},
  "status": "ready",
  "failed_step": null,
  "error": null,
  "generator_version": "post-pipeline-v1",
  "created_at": "2024-01-15T10:00:00",
  "updated_at": "2024-01-15T11:00:00",
  "slide_count": 2,
  "slides": [
    {
      "id": 10,
      "slide_index": 0,
      "slide_type": "cover",
      "pair_index": null,
      "label": "Haushalt",
      "headline": "Was der Rat beschlossen hat",
      "body": null,
      "alt_text": "..."
    }
  ],
  "assets": [
    {
      "id": 20,
      "role": "cover",
      "prompt": "...",
      "path": "output/topic-2024-01-15-01.png",
      "status": "ready",
      "error": null,
      "model": "google/gemini-3.1-flash-image"
    }
  ]
}
```

`post_type` is `summary` or `topic`; post status is `draft`, `ready`, or
`failed`; slide type is `cover`, `heading`, or `continuation`; asset status is
`pending`, `ready`, `fallback`, or `failed`. Slides are ordered by
`slide_index`, assets by `id`. Both `/api/stats` and `/api/pipeline/status`
always include all three post statuses:

```json
"post_counts": {"draft": 2, "ready": 3, "failed": 1}
```

The fetch endpoint is currently unauthenticated; restrict access at the
reverse proxy or add authentication before exposing the service publicly.

## Scheduled jobs

| Job | Schedule (Europe/Berlin) | Description |
| --- | --- | --- |
| `fetch_protocols` | 10:00 and 17:00 | Fetch new protocols from SessionNet |
| `process_protocols` | 10:30 and 17:30 | Reserved post-pipeline slot; currently a no-op |

Because the scheduler runs inside the web process, do not scale the `app`
service to multiple replicas without moving the scheduler to a dedicated
worker first.

## Tests and linting

```bash
pip install -r requirements-dev.txt
pre-commit install --hook-type pre-commit --hook-type pre-push

pytest -m "not manual"   # standard test suite
pytest -m manual         # opt-in real-API tests (none yet)
ruff check .
pre-commit run --all-files
```

The PostgreSQL schema, constraint, and cascade tests are skipped when
`TEST_DATABASE_URL` is unset. Point it at a disposable PostgreSQL database and
run the suite normally:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/gossip_test \
  pytest -m "not manual"
```

Each test creates its own randomly named schema, runs `create_all()` there, and
drops that schema afterwards. Concurrent test sessions do not share tables, and
the `public` schema is never dropped. The database user therefore needs
`CREATE SCHEMA` and `DROP SCHEMA` privileges.

Pipeline tests use `tests/support/fake_llm.py` at the injected LLM port. The
fake scripts responses per role, records every role/prompt/schema/aspect-ratio
call, and can raise transport, schema, or authentication errors. Default tests
never call OpenRouter or any other network service.

Local `pre-commit` hooks run `ruff check` on commit and
`pytest -m "not manual"` before push. There is no remote CI: GitHub Actions has
been removed. Manual tests are excluded from the default run and from hooks.

## Operational notes

- The application prepares `ARTICLES_DIR` for generated images and writes
  monthly logs to `LOGS_DIR`. Both live under `GOSSIP_DATA_DIR` and are
  bind-mounted in `docker-compose.yaml`.
- Docker JSON logs are capped at 10 MB across 3 files; the monthly file logs
  are kept separately so they survive container rebuilds.
- PostgreSQL is only reachable on the internal Compose network.
- The Compose router uses the `web` entrypoint; TLS is expected to terminate
  at the Cloudflare/Traefik edge. Verify the entrypoint against your actual
  Traefik configuration before changing it.
- The API currently has no built-in authentication, rate limiting, or request
  size limits.

## Known limitations / next steps

- The planning stage, both content paths and the Summary visual output are
  implemented; topic visuals, retry/reprocess endpoints, and scheduler wiring
  remain.
- Summary posts are group-pure blue and written as 9:16 story PNGs plus one
  caption file; topic posts remain `draft` until the orange 4:5 carousel
  renderer lands.
- Add Alembic migrations instead of `create_all()`.
- Move the scheduler and long-running pipeline jobs into a dedicated worker.
- Add authentication and rate limiting for the API and pipeline triggers.
- Replace the O(n²) full-text duplicate check with a hash or MinHash index.
- Add structured logging and job-level locking to prevent overlapping runs.
