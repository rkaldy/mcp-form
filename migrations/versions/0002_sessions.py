"""Create form scanning sessions.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade():
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("extracted_data", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "json_valid(extracted_data)", name="ck_sessions_extracted_data_json"
        ),
        sa.CheckConstraint(
            "status IN ('scanning', 'reviewing', 'processing', 'finished')",
            name="ck_sessions_status",
        ),
    )
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"])
    op.create_index("ix_sessions_status", "sessions", ["status"])


def downgrade():
    op.drop_table("sessions")
