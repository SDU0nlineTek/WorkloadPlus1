"""migrate schema from 0.0.4 to 0.0.5

Revision ID: 20260322_000001
Revises:
Create Date: 2026-03-22 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260322_000001"
down_revision = None
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    work_record_columns = _column_names("work_record")
    if work_record_columns and "claimed" not in work_record_columns:
        op.add_column(
            "work_record",
            sa.Column(
                "claimed", sa.Boolean(), nullable=False, server_default=sa.text("0")
            ),
        )

    claim_columns = _column_names("settlement_claim")
    if claim_columns and "paid_minutes" not in claim_columns:
        op.add_column(
            "settlement_claim",
            sa.Column(
                "paid_minutes",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if claim_columns and "volunteer_minutes" not in claim_columns:
        op.add_column(
            "settlement_claim",
            sa.Column(
                "volunteer_minutes",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if claim_columns and "total_minutes" not in claim_columns:
        op.add_column(
            "settlement_claim",
            sa.Column(
                "total_minutes",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    claim_columns = _column_names("settlement_claim")
    if {"paid_hours", "volunteer_hours", "total_hours"}.issubset(claim_columns):
        op.execute(
            "UPDATE settlement_claim "
            "SET paid_minutes = CASE WHEN paid_minutes = 0 THEN CAST(ROUND(paid_hours * 60) AS INTEGER) ELSE paid_minutes END, "
            "volunteer_minutes = CASE WHEN volunteer_minutes = 0 THEN CAST(ROUND(volunteer_hours * 60) AS INTEGER) ELSE volunteer_minutes END, "
            "total_minutes = CASE WHEN total_minutes = 0 THEN CAST(ROUND(total_hours * 60) AS INTEGER) ELSE total_minutes END"
        )


def downgrade() -> None:
    claim_columns = _column_names("settlement_claim")
    if claim_columns:
        with op.batch_alter_table("settlement_claim") as batch_op:
            if "total_minutes" in claim_columns:
                batch_op.drop_column("total_minutes")
            if "volunteer_minutes" in claim_columns:
                batch_op.drop_column("volunteer_minutes")
            if "paid_minutes" in claim_columns:
                batch_op.drop_column("paid_minutes")

    work_record_columns = _column_names("work_record")
    if "claimed" in work_record_columns:
        with op.batch_alter_table("work_record") as batch_op:
            batch_op.drop_column("claimed")
