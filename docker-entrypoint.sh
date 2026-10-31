#!/bin/sh
set -eu

# Apply pending schema migrations before the application starts. The first
# migration is idempotent and also creates the full schema on a fresh database.
alembic upgrade head

exec "$@"
