"""add page_url and publisher_unit to raw_tenders

Revision ID: a1f3c9d2e841
Revises: 6b28fb3f0cae
Create Date: 2026-06-02 08:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a1f3c9d2e841"
down_revision: Union[str, None] = "6b28fb3f0cae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("raw_tenders") as batch_op:
        batch_op.add_column(sa.Column("page_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("publisher_unit", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("raw_tenders") as batch_op:
        batch_op.drop_column("publisher_unit")
        batch_op.drop_column("page_url")
