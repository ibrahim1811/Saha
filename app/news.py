import asyncio
import html
import logging
import re
from itertools import zip_longest

import feedparser

log = logging.getLogger(__name__)

NTV = "https://www.ntv.com.tr/{}.rss"
FEEDS = {
    "gundem": ("Gündem", "https://feeds.bbci.co.uk/turkce/rss.xml"),
    "turkiye": ("Türkiye", NTV.format("turkiye")),
    "dunya": ("Dünya", NTV.format("dunya")),
    "ekonomi": ("Ekonomi", NTV.format("ekonomi")),
    "teknoloji": ("Teknoloji ve bilim", NTV.format("teknoloji")),
    "saglik": ("Sağlık", NTV.format("saglik")),
    "yasam": ("Yaşam", NTV.format("yasam")),
    "egitim": ("Eğitim", NTV.format("egitim")),
    "spor": ("Spor", NTV.format("sporskor")),
    "otomobil": ("Otomobil", NTV.format("otomobil")),
}
CATALOG = [{"key": k, "label": label} for k, (label, _) in FEEDS.items()]

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


def valid_topics(topics) -> list[str]:
    return [t for t in topics or [] if t in FEEDS]


async def _topic(http, topic: str, limit: int) -> list[str]:
    resp = await http.get(FEEDS[topic][1], timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return parse(resp.text, limit)


async def fetch(http, limit: int = 5, topics: list[str] | None = None) -> str:
    topics = valid_topics(topics) or ["gundem"]
    results = await asyncio.gather(*(_topic(http, t, limit) for t in topics), return_exceptions=True)
    lists = []
    for topic, result in zip(topics, results):
        if isinstance(result, BaseException):
            log.warning("Haber konusu alınamadı (%s): %r", topic, result)
        else:
            lists.append(result)
    if not lists:
        raise next(r for r in results if isinstance(r, BaseException))
    picked: list[str] = []
    for row in zip_longest(*lists):
        for summary in row:
            if summary and summary not in picked and len(picked) < limit:
                picked.append(summary)
    return "\n".join(f"• {s}" for s in picked)
