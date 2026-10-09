from datetime import date

import pytest

from app.tasks import TaskError, format_task, format_tasks, is_task_request, parse, parse_result
from tests.fakes import FakeLLM

TODAY = date(2026, 10, 9)


@pytest.mark.parametrize("text,expected", [
    ("fizik ödevi cuma teslim", True),
    ("Matematik SINAVI 20 ekim", True),
    ("kimya sınavım var pazartesi", True),
    ("ödevlerim neler?", False),
    ("sınavım kötü geçti", False),
    ("ödevimi bitirdim", False),
    ("haftaya salı tarih sınavı", True),
    ("edebiyat ödevi 3 kasım", True),
    ("yarın faturayı hatırlat", False),
    ("bugün ne var", False),
])
def test_is_task_request(text, expected):
    assert is_task_request(text) is expected


def test_parse_result_ok():
    assert parse_result({"kind": "odev", "title": " Fizik ödevi ", "due": "2026-10-10"}, TODAY) == ("odev", "Fizik ödevi", date(2026, 10, 10))


def test_parse_result_today_allowed():
    assert parse_result({"kind": "sinav", "title": "Mat", "due": "2026-10-09"}, TODAY)[2] == TODAY


@pytest.mark.parametrize("data", [
    {"kind": "odev", "title": "x", "due": "2026-10-08"},
    {"kind": "proje", "title": "x", "due": "2026-10-10"},
    {"kind": "odev", "title": " ", "due": "2026-10-10"},
    {"kind": "odev", "title": "x", "due": "cuma"},
    {},
    [],
])
def test_parse_result_rejects(data):
    with pytest.raises(TaskError):
        parse_result(data, TODAY)


async def test_parse_sends_today_and_weekday():
    llm = FakeLLM(reply='{"kind": "odev", "title": "Fizik ödevi", "due": "2026-10-16"}')
    assert await parse("fizik ödevi gelecek cuma", TODAY, llm) == ("odev", "Fizik ödevi", date(2026, 10, 16))
    assert "2026-10-09" in llm.calls[0]["prompt"] and "cuma" in llm.calls[0]["prompt"]


@pytest.mark.parametrize("due,label", [
    (date(2026, 10, 9), "bugün"),
    (date(2026, 10, 10), "yarın"),
    (date(2026, 10, 13), "4 gün sonra"),
    (date(2026, 10, 7), "2 gün geçti"),
])
def test_format_task_relative(due, label):
    text = format_task({"id": 3, "kind": "sinav", "title": "Mat sınavı", "due": due, "done": False}, TODAY)
    assert text.startswith("🧪 Mat sınavı") and label in text and "#3" in text


def test_format_tasks_empty_and_done():
    assert format_tasks([], TODAY) == "Yaklaşan ödev ya da sınav yok."
    done = format_task({"id": 1, "kind": "odev", "title": "Fizik", "due": TODAY, "done": True}, TODAY)
    assert done.startswith("✅")



def test_parse_result_not_a_task():
    from app.tasks import NotATask

    with pytest.raises(NotATask):
        parse_result({"kind": None}, TODAY)
