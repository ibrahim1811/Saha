URL = "https://finans.truncgil.com/v4/today.json"
KEYS = {"USD": "Dolar", "EUR": "Euro", "GRA": "Gram altın"}


def _num(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(".", "").replace(",", "."))


def parse(data: dict) -> list[tuple[str, float]]:
    rows = [(label, _num(data[key]["Selling"])) for key, label in KEYS.items() if "Selling" in data.get(key, {})]
    if not rows:
        raise ValueError("Piyasa verisi beklenen formatta değil")
    return rows


def format(rows: list[tuple[str, float]]) -> str:
    return "\n".join(f"{label}: {value:.2f} ₺" for label, value in rows)


async def fetch(http) -> str:
    resp = await http.get(URL, timeout=10)
    resp.raise_for_status()
    return format(parse(resp.json()))
