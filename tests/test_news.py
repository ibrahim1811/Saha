import pytest

from app.news import parse

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Birinci haber</title></item>
<item><title>İkinci haber</title></item>
<item><title>Üçüncü haber</title></item>
</channel></rss>"""


def test_parse_limit():
    assert parse(RSS, limit=2) == ["Birinci haber", "İkinci haber"]


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse("<rss><channel></channel></rss>")


async def test_fetch_respects_limit():
    import httpx

    from app.news import fetch

    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=RSS)))
    assert await fetch(http, 1) == "• Birinci haber"
