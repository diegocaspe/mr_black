"""Crea el administrador inicial (también en producción, donde el seed de desarrollo no se ejecuta).

    python -m app.create_admin --username admin --email admin@mi-dominio.pe --name "Administrador Principal"

La contraseña se toma de ADMIN_PASSWORD; si no está definida se genera una aleatoria y se muestra
una sola vez. No hace nada si ya existe un administrador.
"""

import argparse
import os
import secrets
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.core.validators import validate_password, validate_person_name, validate_username
from app.models import Role, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea el administrador inicial.")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Administrador Principal")
    args = parser.parse_args()

    try:
        username = validate_username(args.username)
        full_name = validate_person_name(args.name)
        password = os.environ.get("ADMIN_PASSWORD") or ("Mb-" + secrets.token_urlsafe(12) + "9a")
        validate_password(password)
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    email = args.email.strip().lower()

    db = SessionLocal()
    try:
        admin_role = db.scalar(select(Role).where(Role.code == "ADMIN"))
        if admin_role is None:
            sys.exit("Error: no existe el rol ADMIN. Aplica primero las migraciones (alembic upgrade head).")
        if db.scalar(select(User.id).where(User.role_id == admin_role.id)):
            print("Ya existe un administrador; no se crea otro.")
            return
        if db.scalar(select(User.id).where((User.username == username) | (User.email == email))):
            sys.exit("Error: el usuario o el correo ya están registrados.")
        db.add(User(username=username, full_name=full_name, email=email, role_id=admin_role.id,
                    password_hash=hash_password(password), is_active=True, is_protected=True,
                    password_changed_at=datetime.now(UTC)))
        db.commit()
    finally:
        db.close()

    print(f"Administrador creado: usuario '{username}'.")
    if not os.environ.get("ADMIN_PASSWORD"):
        print(f"Contraseña generada (se muestra una sola vez, cámbiala al entrar): {password}")


if __name__ == "__main__":
    main()
