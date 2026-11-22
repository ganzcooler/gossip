# Gossip

Gossip is a Python service that fetches municipal council protocols from
[SessionNet](https://sessionnet.owl-it.de/), deduplicates them, and stores them
in PostgreSQL. It runs as a containerized FastAPI application with an
in-process APScheduler.

The stateless post pipeline is feature-complete for generation, retry and
reprocess. A protocol becomes a persisted Redaktionsplan plus one
Summary-Beitrag and zero to five Themenbeiträge with deterministic source
excerpts. Every Beitrag gets a validated writer draft, the hard fact-check gate
with one repair, deterministic slides, a composed caption, Alt-Texte and
rendered images with brand fallbacks. The Summary-Beitrag is a blue 9:16 story;
each Themenbeitrag is an orange 4:5 feed carousel with pair-sliced artwork.
Failed Beiträge can be retried individually from their failed step, and a
protocol can be reprocessed from a fresh plan. `Protocol.processed` becomes true
once the Summary-Beitrag and every planned Themenbeitrag are terminal (`ready` or
`failed`). The legacy one-call article, caption, image, and Instagram pipeline
has been removed; legacy articles remain readable through the API.

## What it does

1. **Fetch** — reads the SessionNet protocol list, downloads new PDFs, and
   extracts their text with PyMuPDF.
2. **Deduplicate** — compares new protocols against the previous 90 days using
   a 95% text-similarity threshold.
3. **Persist and serve** — stores protocols in PostgreSQL, keeps legacy
   articles readable, and exposes protocols, stats, and pipeline status through
   a REST API.
4. **Plan** — the stateless Redaktionsplaner turns a protocol into a plan with
   two to six Summary briefs and zero to five Themenbriefe, including exact
   source anchors. Deterministic steps resolve the official Organ and retrieve
   only the referenced protocol excerpts. The result is persisted as an
   `editorial_plans` row and draft posts.
5. **Summarise** — the Summary-Writer turns the Summary briefs and excerpts
   into a cover title and two to six Summary-Punkte. The Faktenprüfung is a
   hard gate with one repair attempt, and the 9:16 Summary cards are composed
   deterministically at one post-wide body size. The Summary-Beitrag also gets
   a composed caption and deterministic Alt-Texte.
6. **Visualise the Summary** — a stateless visual-prompt call writes the cover
   prompt from the Summary draft only. Image generation requests a 9:16 image
   through the LLM port, center-fits it to exactly 1080×1920, and substitutes
   the deterministic blue brand fallback if the provider or payload fails. The
   renderer writes the cover and two to six cards as
   `summary-<date>-story-<frame>.png` plus exactly one
   `caption-summary-summary.txt` into the protocol folder. Only after the whole
   story and caption are written does the Summary-Beitrag become `ready`.
7. **Write and visualise topics** — for each planned Themenbrief, the
   Themen-Writer sees only that brief and its excerpts and writes an H1 plus
   two to six H2 sections with paragraphs under a hard 3,000-character budget.
   The same Fact-Check gate applies, and the 4:5 content slides are composed
   deterministically: every H2 starts a new slide, overflow continues with the
   short chapter label at one post-wide body size, and the article text is
   never reworded or truncated. A stateless Themen visual-prompt call writes a
   cover and `ceil(content_slides / 2)` pair prompts from the Themenentwurf only.
   Image generation requests 4:5 artwork, normalizes the cover to 1080×1350,
   and center-crops each pair to 720×1350 or a final unpaired strip to
   360×1350. The renderer slices pairs into the zigzag layout and writes
   `topic-<date>-<slide>.png` plus exactly one `caption-topic-<slug>.txt`
   inside the topic's own `topic-<slug>/` subfolder. Themenbeitrag image
   failures produce orange brand fallbacks and the Beitrag still
   becomes `ready`; authentication errors stop the job. Alt-Texte stay in
   PostgreSQL and the API; no JSON, Markdown, prompt, or manifest files are
   written.
8. **Retry and reprocess** — `POST /api/posts/{id}/retry` resets one Beitrag and
   resumes at its `failed_step` with cached drafts, compositions, fact-check
   results, captions and visual prompts. `force=true` clears only that
   Beitrag's content, slides, assets, caption and output files and restarts at
   the writer.
   `POST /api/protocols/{id}/reprocess` deletes the plan, posts and generated
   output and rebuilds the whole protocol. `Protocol.processed` is terminal
   (`ready` or `failed` Beiträge) and a failed Beitrag is never retried
   automatically.

The fetch workflow is triggered by APScheduler and can also be started manually
through the API. The processing job runs the full stateless pipeline for every
unprocessed protocol. It skips protocols whose Redaktionsplan failed (use the
manual reprocess endpoint) and never auto-retries failed Beiträge.

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
├── scheduler.py               APScheduler cron jobs and protocol processing
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
│   ├── topic_renderer.py      Deterministic topic carousel renderer
│   ├── render_common.py       Single brand palette/token source, logo, scrim, badge, folders
│   ├── output_cleanup.py      Scoped force-retry/reprocess file cleanup
│   ├── text_layout.py         Shared font loading, wrapping and fit primitives
│   ├── organs.py              Finite Organ seed and deterministic resolver
│   ├── protocol_excerpts.py   Deterministic source-anchor retrieval
│   └── post_pipeline.py       Plan, content, visuals, retry and reprocess
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
`logo-gossip.png` (transparent RGBA logo, composited directly on the artwork),
`Oswald-var.ttf` (titles, headings, numbers, kickers) and `Inter-var.ttf`
(body copy, badges, page labels). A missing asset is a hard render failure; it
never falls back to another font or logo.

`app/services/render_common.py` is the single source of the brand palette and
render tokens. Both renderers and the deterministic image fallbacks import the
same `SURFACE_*` and `BRAND_*` constants from it; `image_generation.py` owns no
palette of its own.

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
| `GET` | `/api/protocols/{id}/posts` | Summary-Beitrag and Themenbeiträge for a protocol, ordered by `post_index` |
| `GET` | `/api/posts/{id}` | One post with ordered slides and assets |
| `POST` | `/api/posts/{id}/retry?force=false` | Retry one post from `failed_step`, or from the writer with `force=true` |
| `POST` | `/api/protocols/{id}/reprocess` | Rebuild the Redaktionsplan and all posts for a protocol |
| `GET` | `/api/stats` | Protocol/article counts and `post_counts` |
| `POST` | `/api/pipeline/fetch` | Fetch new protocols now |
| `GET` | `/api/pipeline/status` | Pipeline backlog, article counts, and `post_counts` |
| `GET` | `/docs` | Swagger UI |

The fetch endpoint calls the same job as the scheduler. The retry endpoint
returns the same full post shape as `GET /api/posts/{id}`. The old process, run,
and generate-insta triggers are gone.

Planned Beiträge are already persisted and readable. The planning stage stores
the Redaktionsplan and creates the Summary-Beitrag (`slug="summary"`,
`post_index=0`) and zero to five Themenbeiträge as `status="draft"`. The Summary
content path then replaces the Summary-Beitrag's `content_json` with the
validated draft plus source excerpts and fills `content_markdown`,
`slide_plan_json`, `caption`, `alt_text_json`, `fact_check_json` and the
one-based cover/card `post_slides`.
Each Themenbeitrag gets the same persisted fields from its own writer,
fact-check, composition and caption calls, with one-based
cover/heading/continuation `post_slides`. The Summary visual stage writes the
cover prompt and asset row, generates or falls back for the cover art, renders
all 1080×1920 frames in memory, and writes the PNGs plus the caption file
before flipping the Summary-Beitrag to `ready`. Each Themenbeitrag then runs its
own visual-prompt call, generates or falls back for the cover and each pair /
final strip, renders all 1080×1350 frames in memory, writes the carousel images
plus its caption file, and only then flips to `ready`. Rerunning a protocol
reuses a cached Summary or Themenentwurf, composed slides and caption and resumes
at visuals instead of calling the writer again; a `ready` Beitrag is skipped
entirely.
An unknown protocol title marks all planned posts `failed` at `organ`, and a
missing source anchor marks only the affected Beitrag `failed` at
`source_retrieval`. Summary and Themen branches are independent: a Summary
failure at `writer`, `fact_check`, `repair`, `caption`, `slide_composer`,
`visual_prompts`, `image_generation` or `render` does not touch the
Themenentwürfe, and a failed Themenbeitrag does not block the Summary-Beitrag
or the other Themenbeiträge.
Failed Beiträge are not retried automatically on the next run.

### Summary output files

For a protocol titled `Gemeinderat` from 2024-01-15, the renderer writes into
`<ARTICLES_DIR>/240115_gemeinderat/`:

```
summary-2024-01-15-story-01.png   # cover
summary-2024-01-15-story-02.png   # first card
summary-2024-01-15-story-03.png   # second card
caption-summary-summary.txt
```

The folder is reused idempotently. The cover and every card show the transparent
logo directly on the artwork at the top left, without a plate. A Summary-Beitrag
story has three to seven frames (cover plus two to six cards) and exactly one
caption file whose content
is the stored `post.caption`, starting with `Illustration: KI-generiert.` and
carrying the source/date plus the SessionNet link or the manual-link hint. Image
failures produce the blue brand fallback and the Beitrag still becomes `ready`;
authentication errors stop the job immediately. A composition or fit failure
(for example a cover title or card text that cannot be laid out without changing
it) marks the Beitrag `failed` at `slide_composer`. A missing font/logo, a
contrast failure, or an image/caption write failure marks it `failed` at
`render` and writes no partial story; any assets that were already generated are
marked `failed` with the render error.

### Themenbeitrag output files

Each Themenbeitrag writes into its own stable subfolder inside the protocol
folder, for example `<ARTICLES_DIR>/240115_gemeinderat/topic-haushalt/`:

```
topic-2024-01-15-01.png   # cover
topic-2024-01-15-02.png   # first content slide, heading layout
topic-2024-01-15-03.png   # second content slide, continuation layout
topic-2024-01-15-04.png   # third content slide, heading layout
topic-2024-01-15-05.png   # fourth content slide, continuation layout
caption-topic-haushalt.txt
```

Summary files stay flat in the protocol folder. The per-Beitrag subfolder keeps
the exact Themenbeitrag basenames collision-free when a Sitzung has several
Themenbeiträge, and stale-frame cleanup is limited to that Themenbeitrag's
subfolder.

A Themenbeitrag carousel has five to eight images (cover plus four to seven
content slides). Content slides alternate text-left/image-right and
image-left/text-right; each 720×1350 pair artwork is split into the left and
right 360×1350 strips, and an unpaired final slide uses a standalone strip. The
first slide gets the large orange number, one-word kicker, 3 px rule and fitted
H2; continuation slides show the short chapter label, the `n/N` counter and a
1 px hairline. Every content slide carries the transparent logo directly on the
image at the bottom-right of the text block, right-aligned to the 600 px text
column. The caption file is UTF-8, starts with
`Illustration: KI-generiert.` and carries source/date plus the SessionNet link
or the manual-link hint. Image failures produce the orange brand fallback and
the Beitrag still becomes `ready`; authentication errors stop the job. A
composition or fit failure (for example an H1 or H2 that cannot be laid out
without changing it) marks only that Themenbeitrag `failed` at
`slide_composer`. A missing font/logo, a contrast failure, or a PNG/caption
write failure marks only that Themenbeitrag `failed` at `render` and writes no
partial carousel; any generated assets are marked `failed` with the render
error.

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
      "path": "output/240115_gemeinderat/topic-haushalt/topic-2024-01-15-01.png",
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

The API is currently unauthenticated. That includes `POST
/api/posts/{id}/retry`, which spends paid LLM and image budget, and `POST
/api/protocols/{id}/reprocess`, which destructively rebuilds the plan and posts
with paid work. Restrict access at the reverse proxy or add authentication
before exposing the service publicly.

### Retry and reprocess

`POST /api/posts/{id}/retry` resets only that Beitrag to `draft` and reruns it
from its stored `failed_step`. Upstream artifacts are reused:

| Failed step | Retry resumes at |
| --- | --- |
| `writer` (no draft) | Writer, then compose, Faktenprüfung, Caption and visuals |
| `slide_composer` | Compose from the cached draft, then Faktenprüfung, Caption and visuals |
| `fact_check` / `repair` | The Faktenprüfung gate from the cached draft, then Caption and visuals |
| `caption` | Caption from the cached draft; the gate is skipped when `fact_check_json.passed` is true |
| `visual_prompts` | Visual prompts, image generation and render |
| `image_generation` / `render` | Image generation and render with the cached prompts (image bytes are not persisted, so image calls repeat) |
| `organ` | Resolve the Organ again, then continue at the earliest missing cached artifact |
| `source_retrieval` | Retrieve the cached brief's anchors again, then continue at the earliest missing cached artifact |
| unknown / none | Earliest missing cached artifact; the fact-check gate is never bypassed |

`slide_composer` means the draft cannot be composed into Folien, while `render`
means a composed Beitrag cannot be turned into files (missing font/logo,
contrast, or write failure). A render failure marks that Beitrag's generated
assets `failed`; the retry regenerates them from the cached prompts.

`force=true` clears that Beitrag's content, fact-check result, caption, slides,
assets and Alt-Texte, deletes only its generated output, and restarts at the
writer. The Redaktionsplan, briefs and source excerpts stay cached. Other
Beiträge and their files are never touched.

`POST /api/protocols/{id}/reprocess` deletes the existing plan, all posts,
slides and assets, removes only the protocol's generated Summary files and
`topic-*` subfolders, and rebuilds the plan and posts even when the protocol was
already `processed`. A planner failure leaves `processed=false`.

### `Protocol.processed`

`processed` is terminal, not "everything succeeded". It becomes true when a
valid `ready` Redaktionsplan exists, the Summary-Beitrag and every planned
Themenbeitrag exist, and all of them are `ready` or `failed`. A failed
Summary-Beitrag does not block terminal Themenbeiträge, and a failed
Themenbeitrag does not block the Summary-Beitrag. A missing or `draft` Beitrag,
or a failed/missing plan, keeps the protocol unprocessed. Failed Beiträge remain
visible and are only rerun through the manual retry endpoint; the scheduler
never retries them automatically, and it skips protocols with a failed plan so
there is no automatic replan loop.

## Scheduled jobs

| Job | Schedule (Europe/Berlin) | Description |
| --- | --- | --- |
| `fetch_protocols` | 10:00 and 17:00 | Fetch new protocols from SessionNet |
| `process_protocols` | 10:30 and 17:30 | Run the stateless pipeline for unprocessed protocols; skip failed plans and never auto-retry failed posts |

The processing job selects unprocessed protocols once, then processes each one
in its own fresh session and pipeline and commits per protocol. Authentication
or account errors stop the whole job immediately; other per-protocol errors are
logged and the remaining protocols still run.

Because the scheduler runs inside the web process, do not scale the `app`
service to multiple replicas without moving the scheduler to a dedicated
worker first.

## Tests and linting

```bash
pip install -r requirements-dev.txt
pre-commit install --hook-type pre-commit --hook-type pre-push

pytest -m "not manual"   # standard test suite
pytest -m manual         # paid real-API end-to-end smoke test
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

### Manual end-to-end smoke test

`tests/manual/test_e2e_smoke.py` is the only opt-in real-API test. It is marked
`manual`, so `pytest -m "not manual"` and the pre-push hook deselect it. The
test proves the complete pipeline against real systems: a real PostgreSQL
database through `TEST_DATABASE_URL`, real OpenRouter text and image calls
through `OpenRouterLLMClient`, the real FastAPI app through `TestClient`, and
a temporary output directory. It uses no fake LLM and no patched network.

Requirements:

- `TEST_DATABASE_URL`: a disposable PostgreSQL database with a
  `postgresql+asyncpg://` URL. Never point this at production. The test creates
  a unique throwaway schema and refuses to start if the URL is the application
  `DATABASE_URL`.
- `OPENROUTER_API_KEY`: a funded key. The run makes **paid** text and image
  requests and therefore needs network access and real API credit.
- The configured text and image models must be available; see
  `OPENROUTER_TEXT_MODEL` and `OPENROUTER_IMAGE_MODEL`.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/gossip_test \
OPENROUTER_API_KEY=... \
  pytest -m manual tests/manual/test_e2e_smoke.py
```

The test inserts a sanitized `Gemeinderat` fixture protocol (fixed date, no
real personal data), starts the pipeline with
`POST /api/protocols/{id}/reprocess`, and asserts the Summary-Beitrag and
Themenbeiträge, slides, assets, Alt-Texte, image dimensions and names, captions,
and the clean output folder. Output is written under pytest's temporary directory. In a
`finally` block the test deletes the fixture rows, drops the throwaway schema
and removes the generated files. It skips cleanly when `OPENROUTER_API_KEY` or
`TEST_DATABASE_URL` is missing, and it is never part of the default suite.

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
- Force retry and reprocess remove only generated output: Summary
  `summary-*` images plus `caption-summary-*` files, and the affected
  `topic-<slug>/` subfolders. Unrelated files and other Themenbeiträge are left
  alone.
- Docker JSON logs are capped at 10 MB across 3 files; the monthly file logs
  are kept separately so they survive container rebuilds.
- PostgreSQL is only reachable on the internal Compose network.
- The Compose router uses the `web` entrypoint; TLS is expected to terminate
  at the Cloudflare/Traefik edge. Verify the entrypoint against your actual
  Traefik configuration before changing it.
- The API currently has no built-in authentication, rate limiting, or request
  size limits. In particular, retry spends paid LLM/image budget and reprocess
  destructively rebuilds a protocol with paid work.

## Known limitations / next steps

- The planning stage, both content paths, both visual outputs, per-post retry
  and protocol reprocess are implemented; the scheduled processing job is
  wired. The manual real-API end-to-end smoke test is implemented but only
  runs when explicitly requested with real credentials.
- Summary-Beiträge are family-pure blue 9:16 story PNGs; Themenbeiträge are
  family-pure orange 4:5 carousels. Both write only PNGs plus one caption file
  per Beitrag.
- Add Alembic migrations instead of `create_all()`.
- Move the scheduler and long-running pipeline jobs into a dedicated worker.
- Add authentication and rate limiting for the API and pipeline triggers.
- Replace the O(n²) full-text duplicate check with a hash or MinHash index.
- Add structured logging and job-level locking to prevent overlapping runs.
