from datetime import date

from app.briefing import Sources, build


def _ok(text):
    async def f():
        return text
    return f


async def _boom():
    raise RuntimeError("api down")


async def test_all_sections_in_order():
    src = Sources(weather=_ok("Güneşli"), lessons=_ok("• Mat"), finance=_ok("Dolar: 41"), news=_ok("• Haber"))
    text = await build(date(2026, 10, 9), src)
    assert text.startswith("Günaydın Kayra! ☀️ 9 Ekim Cuma")
    assert text.index("🌤 Hava\nGüneşli") < text.index("📚 Bugünün dersleri\n• Mat") < text.index("💱 Piyasa") < text.index("📰 Haberler")


async def test_failed_section_does_not_break_others(caplog):
    src = Sources(weather=_boom, lessons=_ok("• Mat"), finance=_boom, news=_ok("• Haber"))
    text = await build(date(2026, 10, 9), src)
    assert "🌤 Hava\n⚠️ Hava alınamadı" in text
    assert "💱 Piyasa\n⚠️ Piyasa alınamadı" in text
    assert "• Mat" in text and "• Haber" in text
    assert "api down" in caplog.text
