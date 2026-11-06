"""fotos de producto

Revision ID: 5c1e7a9d2b40
Revises: 168b2aa3a159
Create Date: 2026-10-06 16:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5c1e7a9d2b40'
down_revision: Union[str, None] = '168b2aa3a159'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('product_images',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('content_type', sa.String(length=20), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_product_images_size_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_product_images_product_id_products'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_product_images_uploaded_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_images'))
    )
    op.create_index('ix_product_images_product_position', 'product_images', ['product_id', 'position'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_product_images_product_position', table_name='product_images')
    op.drop_table('product_images')
