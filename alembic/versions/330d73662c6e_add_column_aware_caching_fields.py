"""add_column_aware_caching_fields

Revision ID: 330d73662c6e
Revises: 24fcc21ead7a
Create Date: 2025-08-27 20:11:56.735085

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '330d73662c6e'
down_revision: Union[str, Sequence[str], None] = '24fcc21ead7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns for column-aware caching
    op.add_column('processed_files', sa.Column('columns_hash', sa.String(), nullable=True))
    op.add_column('processed_files', sa.Column('cache_key', sa.String(), nullable=True))
    
    # Update existing records with default values
    op.execute("UPDATE processed_files SET columns_hash = 'all_columns'")
    op.execute("UPDATE processed_files SET cache_key = file_hash || '_all_columns'")
    
    # Make columns non-nullable after setting default values
    op.alter_column('processed_files', 'columns_hash', nullable=False)
    op.alter_column('processed_files', 'cache_key', nullable=False)
    
    # Add unique constraint to cache_key (file_hash constraint will be removed by dropping unique property)
    op.create_unique_constraint('processed_files_cache_key_key', 'processed_files', ['cache_key'])
    
    # Add indexes for performance
    op.create_index('ix_processed_files_columns_hash', 'processed_files', ['columns_hash'])
    op.create_index('ix_processed_files_cache_status', 'processed_files', ['cache_key', 'processing_status'])
    
    # Drop old indexes that are no longer optimal
    op.drop_index('ix_processed_files_hash_status', table_name='processed_files')


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse the changes
    op.drop_index('ix_processed_files_cache_status', table_name='processed_files')
    op.drop_index('ix_processed_files_columns_hash', table_name='processed_files')
    
    # Restore old index
    op.create_index('ix_processed_files_hash_status', 'processed_files', ['file_hash', 'processing_status'])
    
    # Remove unique constraint on cache_key
    op.drop_constraint('processed_files_cache_key_key', 'processed_files', type_='unique')
    
    # Drop new columns
    op.drop_column('processed_files', 'cache_key')
    op.drop_column('processed_files', 'columns_hash')
