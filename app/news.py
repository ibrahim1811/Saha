import feedparser

FEED = "https://feeds.bbci.co.uk/turkce/rss.xml"


def parse(xml: str, limit: int = 5) -> list[str]:
    titles = [e.title for e in feedparser.parse(xml).entries[:limit] if getattr(e, "title", "")]
    if not titles:
        raise ValueError("Haber bulunamadı")
    return titles


async def fetch(http) -> str:
    resp = await http.get(FEED, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return "\n".join(f"• {t}" for t in parse(resp.text))
