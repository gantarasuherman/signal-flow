"""signals

Revision ID: 0002_signals
Revises: 0001_candles_settings
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_signals"
down_revision: str | None = "0001_candles_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(4), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("candle_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("entry", sa.Double(), nullable=True),
        sa.Column("stop_loss", sa.Double(), nullable=True),
        sa.Column("take_profit", sa.Double(), nullable=True),
        sa.Column("atr", sa.Double(), nullable=True),
        sa.Column("risk_reward", sa.Double(), nullable=True),
        sa.Column("spread_pips", sa.Double(), nullable=True),
        sa.Column("confidence", sa.Double(), nullable=True),
        sa.Column("confidence_label", sa.String(8), nullable=True),
        sa.Column("entry_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reasons", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("reason_text", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("status", sa.String(8), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_price", sa.Double(), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("result_pips", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["signals.id"],
            name=op.f("fk_signals_parent_id_signals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
        sa.UniqueConstraint(
            "symbol", "strategy", "candle_time", "action", name=op.f("uq_signals_symbol")
        ),
    )
    op.create_index("ix_signals_symbol_created_at", "signals", ["symbol", "created_at"])
    op.create_index(
        "uq_signals_one_active",
        "signals",
        ["symbol", "strategy"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_signals_one_active", table_name="signals")
    op.drop_index("ix_signals_symbol_created_at", table_name="signals")
    op.drop_table("signals")
