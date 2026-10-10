import pytest

from app.news import parse

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Soru haber mi?</title><description>Soru haberin özeti. İkinci cümle.</description></item>
<item><title>Birinci haber</title><description><![CDATA[<p>Birinci haberin özeti.</p> Devamı burada.]]></description></item>
<item><title>Özetsiz haber</title></item>
<item><title>İkinci haber</title><description>İkinci haberin özeti.</description></item>
</channel></rss>"""


def test_parse_returns_first_sentence_and_puts_questions_last():
    assert parse(RSS, limit=3) == ["Birinci haberin özeti.", "İkinci haberin özeti.", "Soru haberin özeti."]


def test_parse_limit():
    assert parse(RSS, limit=1) == ["Birinci haberin özeti."]


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse("<rss><channel></channel></rss>")


async def test_fetch_respects_limit():
    import httpx

    from app.news import fetch

    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=RSS)))
    assert await fetch(http, 1) == "• Birinci haberin özeti."
