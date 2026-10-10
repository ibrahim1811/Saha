import html
import re

import feedparser

FEED = "https://feeds.bbci.co.uk/turkce/rss.xml"

_TAG = re.compile(r"<[^>]+>")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÇĞİÖŞÜ\"'“])")


def _first_sentence(text: str) -> str:
    clean = " ".join(html.unescape(_TAG.sub(" ", text)).split())
    return _SENTENCE_END.split(clean, 1)[0] if clean else ""


def parse(xml: str, limit: int = 5) -> list[str]:
    items = []
    for e in feedparser.parse(xml).entries:
        summary = _first_sentence(getattr(e, "summary", ""))
        if summary:
            items.append((getattr(e, "title", "").strip(), summary))
    items.sort(key=lambda it: it[0].endswith("?"))
    if not items:
        raise ValueError("Haber bulunamadı")
    return [summary for _, summary in items[:limit]]


async def fetch(http, limit: int = 5) -> str:
    resp = await http.get(FEED, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return "\n".join(f"• {s}" for s in parse(resp.text, limit))
