"""Add the protocol session label.

Revision ID: 20261031_0001
Revises:
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 - register metadata
from app.database import Base

revision = "20261031_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "protocols" not in inspector.get_table_names():
        # Fresh database: create the complete schema, including the new column.
        Base.metadata.create_all(bind=bind)
        return

    columns = {column["name"] for column in inspector.get_columns("protocols")}
    if "session_label" not in columns:
        op.add_column(
            "protocols",
            sa.Column("session_label", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "protocols" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("protocols")}
    if "session_label" in columns:
        op.drop_column("protocols", "session_label")
