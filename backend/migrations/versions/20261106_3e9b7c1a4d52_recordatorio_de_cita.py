"""recordatorio de cita: reminder_sent_at e índice de citas por recordar

Revision ID: 3e9b7c1a4d52
Revises: 8a4f2c6e1d93
Create Date: 2026-11-06 12:00:00.000000+00:00

La columna appointments.reminder_sent_at ya venía en el esquema inicial (sin uso hasta ahora);
se agrega con IF NOT EXISTS para que la migración sea segura en cualquier base.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '3e9b7c1a4d52'
down_revision: Union[str, None] = '8a4f2c6e1d93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMP WITH TIME ZONE")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_appointments_reminder_due ON appointments (start_at) "
        "WHERE reminder_sent_at IS NULL AND status IN ('PENDIENTE', 'CONFIRMADA')"
    )


def downgrade() -> None:
    # La columna pertenece al esquema inicial: solo se elimina el índice.
    op.execute("DROP INDEX IF EXISTS ix_appointments_reminder_due")
