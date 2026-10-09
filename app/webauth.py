import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, urlencode


class AuthError(Exception):
    pass


def _digest(pairs: dict, bot_token: str) -> str:
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def verify_init_data(init_data: str, bot_token: str, max_age: int = 86400, now: float | None = None) -> dict:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    if not received or not hmac.compare_digest(_digest(pairs, bot_token), received):
        raise AuthError("Telegram imzası geçersiz")
    try:
        auth_date = int(pairs["auth_date"])
        user = json.loads(pairs["user"])
        int(user["id"])
    except (KeyError, ValueError, TypeError) as e:
        raise AuthError("Telegram verisi eksik") from e
    if (time.time() if now is None else now) - auth_date > max_age:
        raise AuthError("Oturum süresi dolmuş, paneli yeniden aç")
    return user


def sign_init_data(user: dict, bot_token: str, auth_date: int, extra: dict | None = None) -> str:
    pairs = {**(extra or {}), "auth_date": str(auth_date), "user": json.dumps(user, separators=(",", ":"))}
    return urlencode({**pairs, "hash": _digest(pairs, bot_token)})
