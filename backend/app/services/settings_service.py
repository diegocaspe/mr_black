import copy

from sqlalchemy.orm import Session

from app.models.setting import Setting

DEFAULTS: dict[str, dict] = {
    "business": {
        "name": "Mr Black Barbería",
        "legal_name": "Mr Black Barber Shop S.A.C.",
        "ruc": "20601234567",
        "address": "Av. José Larco 345, Miraflores, Lima",
        "phone": "987000111",
        "email": "contacto@mrblack.pe",
    },
    "booking": {
        "slot_interval_minutes": 30,
        "min_notice_minutes": 15,
        "max_days_ahead": 60,
        "client_cancel_min_hours": 2,
    },
    "inventory": {"default_min_stock": 3},
}


def get_setting(db: Session, key: str) -> dict:
    row = db.get(Setting, key)
    value = copy.deepcopy(DEFAULTS.get(key, {}))
    if row:
        value.update(row.value)
    return value


def set_setting(db: Session, key: str, value: dict, user_id: int | None) -> dict:
    row = db.get(Setting, key)
    merged = get_setting(db, key)
    merged.update(value)
    if row:
        row.value = merged
        row.updated_by = user_id
    else:
        db.add(Setting(key=key, value=merged, updated_by=user_id))
    return merged
