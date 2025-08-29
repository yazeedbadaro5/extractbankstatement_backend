"""add_columns_field_to_processed_files

Revision ID: b12598ffff89
Revises: 330d73662c6e
Create Date: 2025-08-28 20:29:30.251468

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b12598ffff89'
down_revision: Union[str, Sequence[str], None] = '330d73662c6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add columns field to store actual column names."""
    # Add new columns field
    op.add_column('processed_files', sa.Column('columns', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove columns field."""
    # Drop columns field
    op.drop_column('processed_files', 'columns')
