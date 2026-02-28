# AGENTS.md - Architect Mode

This file provides guidance to agents when designing architecture for this repository.

## Architectural Constraints

**Dual Codebase Design:**
- `app/` (FastAPI) and `src/` (legacy) are intentionally separate
- `src/` pipeline steps remain synchronous for standalone use
- `app/services/pipeline_adapter.py` bridges async/sync gap
- Do not refactor `src/` to be async - would break standalone usage

**Database Design:**
- PostgreSQL with async SQLAlchemy (asyncpg driver)
- Models use explicit indexes via `__table_args__` for query performance
- Foreign keys use `ondelete="CASCADE"` - intentional for protocol deletion
- `Protocol` → `Article` one-to-many with `back_populates`

**Scheduler Architecture:**
- APScheduler runs as part of FastAPI lifespan
- Two jobs: fetch (10:00, 17:00) and process (10:30, 17:30)
- Jobs use wrapper functions to manage DB sessions and transactions
- Scheduler stops cleanly on application shutdown

**Path System Duality:**
- Docker container: absolute paths (`/app/articles`)
- Local execution: `PROJECT_ROOT` relative paths
- Bind mounts in docker-compose sync host and container directories
- Never hardcode paths - always use config constants

**AI Integration:**
- Google GenAI SDK with specific model assignments
- 4:5 aspect ratio images required for Instagram (no crop needed)
- API rate limiting via `API_CALL_DELAY_SECONDS` (1 second)
- Image generation returns bytes, not URLs

**Security Considerations:**
- Traefik handles HTTPS termination externally
- No auth on API endpoints (internal use only)
- Environment variables for all secrets
- Database credentials via env, not hardcoded