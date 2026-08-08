"""merge web library and MCP migration branches

Revision ID: f6a7b8c9d0e1
Revises: d3f4a5b6c7d8, e5f6a7b8c9d0
Create Date: 2026-08-08
"""

from typing import Sequence, Union


revision: str = "f6a7b8c9d0e1"
down_revision: tuple[str, str] = (
    "d3f4a5b6c7d8",
    "e5f6a7b8c9d0",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
