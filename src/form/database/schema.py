"""SQLAlchemy schema definitions used exclusively by Alembic migrations."""

from sqlalchemy import CheckConstraint, Column, Index, MetaData, Table, Text

metadata = MetaData()


sessions = Table(
    "sessions",
    metadata,
    Column("session_id", Text, primary_key=True),
    Column("created_at", Text, nullable=False),
    Column("extracted_data", Text, nullable=False),
    Column("status", Text, nullable=False),
    CheckConstraint(
        "json_valid(extracted_data)", name="ck_sessions_extracted_data_json"
    ),
    CheckConstraint(
        "status IN ('scanning', 'reviewing', 'processing', 'finished')",
        name="ck_sessions_status",
    ),
    Index("ix_sessions_created_at", "created_at"),
    Index("ix_sessions_status", "status"),
)
