import logging

from app.status import ErrorBuffer


def test_buffer_keeps_errors_newest_first_and_limits():
    buf = ErrorBuffer(size=3)
    log = logging.getLogger("t.status")
    log.addHandler(buf)
    log.info("bilgi")
    for i in range(5):
        try:
            raise ValueError(f"hata{i}")
        except ValueError:
            log.exception("başarısız %s", i)
    log.removeHandler(buf)
    items = buf.records()
    assert [r["message"] for r in items] == ["başarısız 4", "başarısız 3", "başarısız 2"]
    assert "hata4" in items[0]["error"] and items[0]["logger"] == "t.status"
