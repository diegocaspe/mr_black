"""Reglas centrales de validación (0024803, 0024792, 0024829, 0024828, 0022634, 0024831)."""

from datetime import date
from decimal import Decimal

import pytest

from app.core import validators as v


@pytest.mark.parametrize("raw", ["987654321", "987 654 321", "987-654-321", " 987 - 654 - 321 ", "+51 987 654 321", "(987) 654-321"])
def test_phone_normalizes_to_single_format(raw):
    assert v.normalize_phone(raw) == "987654321"


@pytest.mark.parametrize("raw", ["654 - 876 - 432", "98765432", "9876543210", "98765432a", "abc", "", "887654321"])
def test_phone_rejects_invalid(raw):
    with pytest.raises(ValueError):
        v.normalize_phone(raw)


@pytest.mark.parametrize("name", ["Carlos Mendoza", "José Ñúñez", "  Ana   María  "])
def test_person_name_valid(name):
    assert v.validate_person_name(name) == " ".join(name.split())


@pytest.mark.parametrize("name", ["Carl0s", "Ana$", "A", "x" * 61, "<script>", "Juan_Perez"])
def test_person_name_invalid(name):
    with pytest.raises(ValueError):
        v.validate_person_name(name)


@pytest.mark.parametrize("pwd", ["1234", "abcdefgh", "12345678", "password1", "short1a"])
def test_password_policy_rejects_weak(pwd):
    with pytest.raises(ValueError):
        v.validate_password(pwd)


def test_password_policy_accepts_strong():
    assert v.validate_password("Barba2026segura")
    assert v.password_strength("abc") == 0
    assert v.password_strength("Barba2026Segura!") == 4


@pytest.mark.parametrize("value", ["0.000000000001", "0", "0.09", "1.999", "-5", "abc", "100000.00", "NaN", "Infinity"])
def test_price_invalid(value):
    with pytest.raises(ValueError):
        v.validate_price(value)


@pytest.mark.parametrize("value,expected", [("0.10", "0.10"), ("25.9", "25.90"), (18, "18.00"), ("10.000", "10.00")])
def test_price_valid(value, expected):
    assert v.validate_price(value) == Decimal(expected)


@pytest.mark.parametrize("value", ["5.5", "-0.1", "4.55", "abc", "10"])
def test_rating_invalid(value):
    with pytest.raises(ValueError):
        v.validate_rating(value)


def test_rating_keeps_exact_value():
    assert v.validate_rating("4.5") == Decimal("4.5")
    assert v.validate_rating("0") == Decimal("0.0")


@pytest.mark.parametrize("name", ["$$AAAA", "Gel<script>", "Ce", "Gel@Mr", "x" * 61, "1234"])
def test_product_name_invalid(name):
    with pytest.raises(ValueError):
        v.validate_product_name(name)


@pytest.mark.parametrize("name", ["Gel Mr Black", "Cera Matte 2.0", "Shampoo Anti-caspa", "Aceite N.5"])
def test_product_name_valid(name):
    assert v.validate_product_name(name) == name


@pytest.mark.parametrize("url", ["javascript:alert(1)", "notaurl", "ftp://x.com/a.png", "https://" + "a" * 500 + ".com", "http://x y.com/a.png", "https://localhost-only"])
def test_image_url_invalid(url):
    with pytest.raises(ValueError):
        v.validate_image_url(url)


def test_image_url_valid_and_empty():
    assert v.validate_image_url("https://i.pravatar.cc/320?img=12")
    assert v.validate_image_url("") is None


@pytest.mark.parametrize("d", [date(1, 1, 1), date(1999, 12, 31), date(2100, 1, 1)])
def test_report_date_bounds(d):
    with pytest.raises(ValueError):
        v.validate_report_date(d)
