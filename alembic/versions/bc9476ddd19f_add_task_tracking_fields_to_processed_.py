"""add_task_tracking_fields_to_processed_files

Revision ID: bc9476ddd19f
Revises: 484512949f78
Create Date: 2025-09-02 17:30:30.900148

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc9476ddd19f'
down_revision: Union[str, Sequence[str], None] = '484512949f78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add task tracking fields to processed_files table."""
    # Add task_id field for linking Redis tasks to database records
    op.add_column('processed_files', sa.Column('task_id', sa.String(), nullable=True))
    
    # Add client_ip field for anonymous user task recovery
    op.add_column('processed_files', sa.Column('client_ip', sa.String(), nullable=True))
    
    # Add indexes for efficient querying
    op.create_index('ix_processed_files_task_id', 'processed_files', ['task_id'])
    op.create_index('ix_processed_files_client_ip', 'processed_files', ['client_ip'])


def downgrade() -> None:
    """Remove task tracking fields from processed_files table."""
    # Drop indexes first
    op.drop_index('ix_processed_files_client_ip', table_name='processed_files')
    op.drop_index('ix_processed_files_task_id', table_name='processed_files')
    
    # Drop columns
    op.drop_column('processed_files', 'client_ip')
    op.drop_column('processed_files', 'task_id')
