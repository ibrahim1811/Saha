import io
import math
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.weather import CONDITION_TR, DayWeather

S = 2
SIZE = 1080
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
PALETTES = {
    "clear": ((40, 112, 238), (255, 160, 98)),
    "partly": ((58, 108, 196), (150, 186, 232)),
    "cloudy": ((78, 92, 120), (146, 160, 182)),
    "fog": ((108, 118, 132), (186, 192, 200)),
    "rain": ((30, 52, 98), (84, 116, 168)),
    "storm": ((24, 24, 52), (78, 66, 120)),
    "snow": ((106, 148, 204), (220, 232, 250)),
}
WHITE = (255, 255, 255)
SUN = (255, 208, 74)


def tr_capitalize(text: str) -> str:
    if not text:
        return text
    first = {"i": "İ", "ı": "I"}.get(text[0], text[0].upper())
    return first + text[1:]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size * S)


def _p(*values):
    return tuple(v * S for v in values)


def _gradient(top, bottom) -> Image.Image:
    img = Image.new("RGB", (1, SIZE * S))
    for y in range(SIZE * S):
        t = y / (SIZE * S - 1)
        img.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img.resize((SIZE * S, SIZE * S)).convert("RGBA")


def _sun(d: ImageDraw.ImageDraw, cx, cy, r):
    for i in range(8):
        a = i * math.pi / 4
        d.line(_p(cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35, cx + math.cos(a) * r * 1.75, cy + math.sin(a) * r * 1.75),
               fill=SUN, width=int(r * 0.16 * S))
    d.ellipse(_p(cx - r, cy - r, cx + r, cy + r), fill=SUN)


def _cloud(d: ImageDraw.ImageDraw, cx, cy, w, color):
    h = w * 0.42
    d.rounded_rectangle(_p(cx - w / 2, cy, cx + w / 2, cy + h), radius=h / 2 * S, fill=color)
    d.ellipse(_p(cx - w * 0.36, cy - h * 0.55, cx + w * 0.02, cy + h * 0.75), fill=color)
    d.ellipse(_p(cx - w * 0.12, cy - h * 0.95, cx + w * 0.34, cy + h * 0.6), fill=color)


def _icon(d: ImageDraw.ImageDraw, cond: str, cx, cy):
    if cond == "clear":
        _sun(d, cx, cy, 70)
    elif cond in ("partly", ""):
        _sun(d, cx - 45, cy - 45, 55)
        _cloud(d, cx + 15, cy, 200, (250, 250, 255))
    elif cond == "cloudy":
        _cloud(d, cx - 40, cy - 40, 150, (210, 216, 228))
        _cloud(d, cx + 10, cy, 210, (245, 246, 250))
    elif cond == "fog":
        for i, w in enumerate((200, 240, 180)):
            y = cy - 50 + i * 50
            d.rounded_rectangle(_p(cx - w / 2, y, cx + w / 2, y + 22), radius=11 * S, fill=(240, 242, 246))
    elif cond in ("rain", "storm", "snow"):
        color = (200, 204, 222) if cond == "storm" else (245, 246, 250)
        _cloud(d, cx, cy - 40, 220, color)
        if cond == "rain":
            for i in range(4):
                x = cx - 70 + i * 45
                d.line(_p(x, cy + 70, x - 18, cy + 120), fill=(140, 200, 255), width=10 * S)
        elif cond == "snow":
            for i in range(4):
                x = cx - 70 + i * 45
                d.ellipse(_p(x - 9, cy + 85, x + 9, cy + 103), fill=WHITE)
        else:
            d.polygon(_p(cx - 2, cy + 45, cx - 32, cy + 95, cx - 4, cy + 95, cx - 18, cy + 140, cx + 32, cy + 78, cx + 4, cy + 78, cx + 18, cy + 45),
                      fill=SUN)
    else:
        _sun(d, cx - 45, cy - 45, 55)
        _cloud(d, cx + 15, cy, 200, (250, 250, 255))


def _pill(d: ImageDraw.ImageDraw, x, y, label: str, value: str) -> int:
    lf, vf = _font(24), _font(36, bold=True)
    w = max(d.textlength(label, font=lf), d.textlength(value, font=vf)) / S + 56
    d.rounded_rectangle(_p(x, y, x + w, y + 112), radius=28 * S, fill=(255, 255, 255, 46))
    d.text(_p(x + 28, y + 16), label, font=lf, fill=(255, 255, 255, 210))
    d.text(_p(x + 28, y + 50), value, font=vf, fill=WHITE)
    return int(w)


def _chart(d: ImageDraw.ImageDraw, hourly: tuple[float, ...], x0, y0, x1, y1):
    hours = list(range(6, 24))
    temps = [hourly[h] for h in hours]
    lo, hi = min(temps), max(temps)
    span = max(hi - lo, 4)
    base = (lo + hi) / 2 - span / 2
    pts = [(x0 + (x1 - x0) * i / (len(hours) - 1), y1 - 40 - (t - base) / span * (y1 - y0 - 110)) for i, t in enumerate(temps)]
    d.polygon(_p(*[c for p in pts for c in p], x1, y1 - 40, x0, y1 - 40), fill=(255, 255, 255, 40))
    d.line(_p(*[c for p in pts for c in p]), fill=WHITE, width=6 * S, joint="curve")
    lf, tf = _font(24), _font(28, bold=True)
    for i, h in enumerate(hours):
        if h % 3:
            continue
        px, py = pts[i]
        d.ellipse(_p(px - 9, py - 9, px + 9, py + 9), fill=WHITE)
        label = f"{temps[i]:.0f}°"
        d.text(_p(px - d.textlength(label, font=tf) / S / 2, py - 52), label, font=tf, fill=WHITE)
        hour = f"{h:02d}:00"
        d.text(_p(px - d.textlength(hour, font=lf) / S / 2, y1 - 28), hour, font=lf, fill=(255, 255, 255, 200))


def render_card(w: DayWeather, hints: list[str], today: date) -> bytes:
    top, bottom = PALETTES.get(w.condition, PALETTES["partly"])
    img = _gradient(top, bottom)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    d.text(_p(72, 64), "BUCA · İZMİR", font=_font(30, bold=True), fill=(255, 255, 255, 220))
    d.text(_p(72, 108), f"{today.day} {MONTHS[today.month - 1]} {DAYS[today.weekday()]}", font=_font(44), fill=WHITE)
    _icon(d, w.condition, 860, 170)

    big = f"{w.t_max:.0f}°"
    big_font = _font(250, bold=True)
    d.text(_p(60, 170), big, font=big_font, fill=WHITE)
    bx = 60 + d.textlength(big, font=big_font) / S + 24
    d.text(_p(bx, 290), CONDITION_TR.get(w.condition, "Bugün"), font=_font(46, bold=True), fill=WHITE)
    d.text(_p(bx, 352), f"en düşük {w.t_min:.0f}° · en yüksek {w.t_max:.0f}°", font=_font(30), fill=(255, 255, 255, 220))

    x = 72
    for label, value in (("Yağış", f"%{w.rain_prob}"), ("Rüzgâr", f"{w.wind_max:.0f} km/s"),
                         ("Sabah · Akşam", f"{w.t_morning:.0f}° · {w.t_evening:.0f}°")):
        x += _pill(d, x, 480, label, value) + 20

    if len(w.hourly) == 24:
        _chart(d, w.hourly, 100, 640, 980, 900)
    else:
        d.text(_p(72, 700), "Saatlik veri yok", font=_font(30), fill=(255, 255, 255, 200))

    chips = [tr_capitalize(h) for h in hints] or ["Rahat giyin"]
    x, cf = 72, _font(30, bold=True)
    for chip in chips:
        cw = d.textlength(chip, font=cf) / S + 48
        if x + cw > SIZE - 72:
            break
        d.rounded_rectangle(_p(x, 940, x + cw, 1000), radius=30 * S, fill=(255, 255, 255, 235))
        d.text(_p(x + 24, 948), chip, font=cf, fill=top)
        x += cw + 14
    d.text(_p(SIZE - 150, 1030), "Saha", font=_font(26, bold=True), fill=(255, 255, 255, 160))

    out = Image.alpha_composite(img, layer).convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
