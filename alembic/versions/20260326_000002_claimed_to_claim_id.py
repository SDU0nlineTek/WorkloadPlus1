"""replace work_record.claimed with claim_id relation

Revision ID: 20260326_000002
Revises: 20260322_000001
Create Date: 2026-03-26 00:00:02
"""

from __future__ import annotations

from alembic import op  # type: ignore[import-not-found]
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260326_000002"
down_revision = "20260322_000001"
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
    if not work_record_columns:
        return

    if "claim_id" not in work_record_columns:
        op.add_column("work_record", sa.Column("claim_id", sa.String(length=32), nullable=True))
        op.create_index("ix_work_record_claim_id", "work_record", ["claim_id"], unique=False)

    work_record_columns = _column_names("work_record")
    if "claimed" in work_record_columns and _column_names("settlement_period") and _column_names("settlement_claim"):
        op.execute(
            "UPDATE work_record "
            "SET claim_id = ("
            "  SELECT sc.id FROM settlement_claim sc "
            "  JOIN settlement_period sp ON sp.id = sc.period_id "
            "  WHERE sc.user_id = work_record.user_id "
            "    AND sp.dept_id = work_record.dept_id "
            "    AND work_record.created_at >= sp.start_date "
            "    AND work_record.created_at <= sp.end_date "
            "  ORDER BY sc.submitted_at DESC "
            "  LIMIT 1"
            ") "
            "WHERE claim_id IS NULL AND claimed = 1"
        )

    if "claimed" in work_record_columns:
        with op.batch_alter_table("work_record") as batch_op:
            batch_op.drop_column("claimed")


def downgrade() -> None:
    work_record_columns = _column_names("work_record")
    if not work_record_columns:
        return

    if "claimed" not in work_record_columns:
        op.add_column("work_record", sa.Column("claimed", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    work_record_columns = _column_names("work_record")
    if "claim_id" in work_record_columns:
        op.execute("UPDATE work_record SET claimed = 1 WHERE claim_id IS NOT NULL")
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        index_names = {
            idx["name"] for idx in inspector.get_indexes("work_record") if idx.get("name")
        }
        with op.batch_alter_table("work_record") as batch_op:
            if "ix_work_record_claim_id" in index_names:
                batch_op.drop_index("ix_work_record_claim_id")
            batch_op.drop_column("claim_id")
