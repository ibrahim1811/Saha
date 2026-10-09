from app.db import clean_dsn


def test_removes_channel_binding_keeps_sslmode():
    url = "postgresql://u:p@ep-x.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert clean_dsn(url) == "postgresql://u:p@ep-x.neon.tech/neondb?sslmode=require"


def test_plain_url_untouched():
    assert clean_dsn("postgresql://u:p@localhost/db") == "postgresql://u:p@localhost/db"
