"""merge web library and ingestion completion migration branches

Revision ID: a7b8c9d0e1f2
Revises: d3f4a5b6c7d8, f6a7b8c9d0e1
Create Date: 2026-08-09
"""

from typing import Sequence, Union


revision: str = "a7b8c9d0e1f2"
down_revision: tuple[str, str] = (
    "d3f4a5b6c7d8",
    "f6a7b8c9d0e1",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
