from datetime import UTC, date, datetime, time, timedelta

from app.core.config import get_settings


def tz():
    return get_settings().tz


def now_local() -> datetime:
    return datetime.now(tz())


def today_local() -> date:
    return now_local().date()


def to_aware(dt: datetime) -> datetime:
    """Fechas sin zona se interpretan en la zona horaria de la barbería."""
    return dt.replace(tzinfo=tz()) if dt.tzinfo is None else dt


def local_dt(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=tz())


def day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=tz())
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)
