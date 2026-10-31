# Database migrations

The application still creates missing tables with SQLAlchemy `create_all()` on
startup. Alembic is used for incremental schema changes on existing databases.

## Apply migrations

Inside the running app container:

```bash
alembic upgrade head
```

Or from Docker Compose:

```bash
docker compose run --rm app alembic upgrade head
```

The database URL is read from `DATABASE_URL` (or the `DB_*` values in `.env`).

## Create a new migration

```bash
alembic revision --autogenerate -m "describe the change"
```

Review the generated file before committing it. The first migration is written
to be idempotent: it creates the full schema on a fresh database and only adds
the missing `protocols.session_label` column on an existing one.
