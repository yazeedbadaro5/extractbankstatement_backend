"""seed_all_subscription_plans

Revision ID: 68307ccebd71
Revises: ac6b03077891
Create Date: 2025-08-17 19:11:12.589887

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '68307ccebd71'
down_revision: Union[str, Sequence[str], None] = 'ac6b03077891'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reorganize subscription plans with proper tier-based IDs."""
    # NOTE: This migration was applied manually via direct database updates
    # to reorganize existing subscription plans by tier:
    # ID 1: Free Plan (0 credits, $0.00)
    # ID 2: Basic Plan (100 credits, $9.99/month) 
    # ID 3: Pro Plan (500 credits, $29.99/month)
    # ID 4: Enterprise Plan (10,000 credits, $99.99/month)
    pass


def downgrade() -> None:
    """Remove all seeded subscription plans."""
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM subscription_plans"))
