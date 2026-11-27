"""Allow sessions to enter the form normalization phase.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade():
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint("ck_sessions_status", type_="check")
        batch.create_check_constraint(
            "ck_sessions_status",
            "status IN ('normalizing', 'scanning', 'reviewing', 'processing', 'finished')",
        )


def downgrade():
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint("ck_sessions_status", type_="check")
        batch.create_check_constraint(
            "ck_sessions_status",
            "status IN ('scanning', 'reviewing', 'processing', 'finished')",
        )
