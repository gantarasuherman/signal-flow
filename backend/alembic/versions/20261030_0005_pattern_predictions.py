"""pattern_predictions

Revision ID: 0005_pattern_predictions
Revises: 0004_backtest_runs
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_pattern_predictions"
down_revision: str | None = "0004_backtest_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pattern_predictions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(4), nullable=False),
        sa.Column("pattern", sa.String(32), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("chance", sa.Double(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("pattern_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Double(), nullable=False),
        sa.Column("spread_pips", sa.Double(), nullable=False),
        sa.Column("exit_price", sa.Double(), nullable=True),
        sa.Column("result_pips", sa.Double(), nullable=True),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("on_time", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pattern_predictions")),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            "pattern_time",
            "pattern",
            name=op.f("uq_pattern_predictions_symbol"),
        ),
    )
    op.create_index(
        "ix_pattern_predictions_status_close", "pattern_predictions", ["status", "close_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_pattern_predictions_status_close", table_name="pattern_predictions")
    op.drop_table("pattern_predictions")
