import pytest

from app.webauth import AuthError, sign_init_data, verify_init_data

TOKEN = "123:abc"
USER = {"id": 42, "first_name": "Kayra"}


def test_valid_roundtrip():
    data = sign_init_data(USER, TOKEN, 1_000_000)
    assert verify_init_data(data, TOKEN, now=1_000_100)["id"] == 42


def test_extra_fields_are_signed():
    data = sign_init_data(USER, TOKEN, 1_000_000, extra={"query_id": "AAA", "signature": "xyz"})
    assert verify_init_data(data, TOKEN, now=1_000_000)["id"] == 42


def test_wrong_token_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign_init_data(USER, TOKEN, 1_000_000), "999:zzz", now=1_000_000)


def test_tampered_user_rejected():
    data = sign_init_data(USER, TOKEN, 1_000_000).replace("42", "43")
    with pytest.raises(AuthError):
        verify_init_data(data, TOKEN, now=1_000_000)


def test_expired_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign_init_data(USER, TOKEN, 1_000_000), TOKEN, now=1_000_000 + 86_401)


@pytest.mark.parametrize("data", ["", "auth_date=1", "hash=abc&auth_date=1"])
def test_garbage_rejected(data):
    with pytest.raises(AuthError):
        verify_init_data(data, TOKEN, now=1)


def test_future_auth_date_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign_init_data(USER, TOKEN, 1_000_000 + 3600), TOKEN, now=1_000_000)
