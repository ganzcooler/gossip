# AGENTS.md - Debug Mode

This file provides guidance to agents when debugging code in this repository.

## Debug-Specific Rules

**Logging:**
- Logs written to both console and timestamped files in `logs/` directory
- Log format: `'%(asctime)s %(levelname)s %(name)s: %(message)s'`
- Use `app.logging_config.setup_logging()` for FastAPI, `src.pipeline_steps.setup_logger` for pipeline

**Common Issues:**
- `.env` file must exist in project root or app exits with error (checked in `main.py`)
- Missing `GOOGLE_API_KEY` causes `ValueError` from `src/config.py:load_google_api_key()`
- Database connection failures: check `DATABASE_URL` format (must be asyncpg)

**Scheduler Debugging:**
- APScheduler jobs run via wrappers in `app/scheduler.py`
- Jobs auto-commit on success, rollback on exception
- Check logs for "Fetch protocols job failed" or "Process protocols job failed"

**Duplicate Detection:**
- Uses 95% similarity threshold on last 3 months of protocols
- Check `app/services/duplicate_detector.py` for logic

**Path Issues:**
- Docker: absolute paths (`/app/articles`)
- Local: relative from `PROJECT_ROOT` (`src/config.py:10`)
- Mixing path systems causes file not found errors

**Database:**
- Use `alembic history` to check migration status
- Migrations stored in `alembic/versions/`
- PostgreSQL healthcheck: `pg_isready -U ${DB_USER} -d ${DB_NAME}`