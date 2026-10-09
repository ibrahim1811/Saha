import pytest

from app.finance import format, parse


def test_parse_numbers_and_strings():
    data = {
        "USD": {"Selling": 41.2345},
        "EUR": {"Selling": "48,10"},
        "GRA": {"Selling": "4.312,55"},
    }
    assert parse(data) == [("Dolar", 41.2345), ("Euro", 48.10), ("Gram altın", 4312.55)]


def test_parse_skips_missing():
    assert parse({"USD": {"Selling": 41}}) == [("Dolar", 41.0)]


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse({"Update_Date": "x"})


def test_format():
    assert format([("Dolar", 41.2345), ("Gram altın", 4312.5)]) == "Dolar: 41.23 ₺\nGram altın: 4312.50 ₺"
