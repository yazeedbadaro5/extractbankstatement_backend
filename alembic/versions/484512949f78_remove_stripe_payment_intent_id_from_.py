"""remove_stripe_payment_intent_id_from_transactions

Revision ID: 484512949f78
Revises: b12598ffff89
Create Date: 2025-08-28 21:42:30.926318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '484512949f78'
down_revision: Union[str, Sequence[str], None] = 'b12598ffff89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Remove the stripe_payment_intent_id column from transactions table
    op.drop_column('transactions', 'stripe_payment_intent_id')


def downgrade() -> None:
    """Downgrade schema."""
    # Add back the stripe_payment_intent_id column
    op.add_column('transactions', sa.Column('stripe_payment_intent_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_transactions_stripe_payment_intent_id'), 'transactions', ['stripe_payment_intent_id'], unique=False)
