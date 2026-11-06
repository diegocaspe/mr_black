"""ficha de servicio: contenido y fotos

Revision ID: 8a4f2c6e1d93
Revises: 5c1e7a9d2b40
Create Date: 2026-10-07 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '8a4f2c6e1d93'
down_revision: Union[str, None] = '5c1e7a9d2b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('services', sa.Column('details', sa.String(length=1000), nullable=True))
    op.add_column('services', sa.Column('includes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('services', sa.Column('offer', sa.String(length=120), nullable=True))
    op.create_table('service_images',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('service_id', sa.BigInteger(), nullable=False),
    sa.Column('content_type', sa.String(length=20), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_service_images_size_positive')),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_service_images_service_id_services'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_service_images_uploaded_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_images'))
    )
    op.create_index('ix_service_images_service_position', 'service_images', ['service_id', 'position'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_service_images_service_position', table_name='service_images')
    op.drop_table('service_images')
    op.drop_column('services', 'offer')
    op.drop_column('services', 'includes')
    op.drop_column('services', 'details')
