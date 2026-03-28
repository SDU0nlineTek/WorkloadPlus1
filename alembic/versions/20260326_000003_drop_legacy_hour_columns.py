"""drop legacy settlement_claim hour columns

Revision ID: 20260326_000003
Revises: 20260326_000002
Create Date: 2026-03-26 00:00:03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260326_000003"
down_revision = "20260326_000002"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    claim_columns = _column_names("settlement_claim")
    if not claim_columns:
        return

    with op.batch_alter_table("settlement_claim") as batch_op:
        if "paid_hours" in claim_columns:
            batch_op.drop_column("paid_hours")
        if "volunteer_hours" in claim_columns:
            batch_op.drop_column("volunteer_hours")
        if "total_hours" in claim_columns:
            batch_op.drop_column("total_hours")


def downgrade() -> None:
    claim_columns = _column_names("settlement_claim")
    if not claim_columns:
        return

    with op.batch_alter_table("settlement_claim") as batch_op:
        if "paid_hours" not in claim_columns:
            batch_op.add_column(
                sa.Column(
                    "paid_hours",
                    sa.Float(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
        if "volunteer_hours" not in claim_columns:
            batch_op.add_column(
                sa.Column(
                    "volunteer_hours",
                    sa.Float(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
        if "total_hours" not in claim_columns:
            batch_op.add_column(
                sa.Column(
                    "total_hours",
                    sa.Float(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )

    if {"paid_minutes", "volunteer_minutes", "total_minutes"}.issubset(
        _column_names("settlement_claim")
    ):
        op.execute(
            "UPDATE settlement_claim "
            "SET paid_hours = ROUND(COALESCE(paid_minutes, 0) / 60.0, 2), "
            "volunteer_hours = ROUND(COALESCE(volunteer_minutes, 0) / 60.0, 2), "
            "total_hours = ROUND(COALESCE(total_minutes, 0) / 60.0, 2)"
        )
