"""merge ingest notification delivery migration branch

Revision ID: b2c3d4e5f6a7
Revises: a7b8c9d0e1f2, a1b2c3d4e5f6
Create Date: 2026-08-09
"""

from typing import Sequence, Union


revision: str = "b2c3d4e5f6a7"
down_revision: tuple[str, str] = (
    "a7b8c9d0e1f2",
    "a1b2c3d4e5f6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
