"""candles dan instrument_settings

Revision ID: 0001_candles_settings
Revises:
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_candles_settings"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candles",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(4), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Double(), nullable=False),
        sa.Column("high", sa.Double(), nullable=False),
        sa.Column("low", sa.Double(), nullable=False),
        sa.Column("close", sa.Double(), nullable=False),
        sa.Column("volume", sa.Double(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("symbol", "timeframe", "open_time", name=op.f("pk_candles")),
    )
    op.create_table(
        "instrument_settings",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("price_offset", sa.Double(), server_default="0", nullable=False),
        sa.Column("broker_price", sa.Double(), nullable=True),
        sa.Column("feed_price", sa.Double(), nullable=True),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spread_pips", sa.Double(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("symbol", name=op.f("pk_instrument_settings")),
    )


def downgrade() -> None:
    op.drop_table("instrument_settings")
    op.drop_table("candles")
