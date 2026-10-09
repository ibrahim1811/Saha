from app.textutil import split_message


def test_short_untouched():
    assert split_message("merhaba") == ["merhaba"]


def test_splits_on_newlines():
    text = "\n".join(["a" * 30] * 10)
    parts = split_message(text, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "\n".join(parts) == text


def test_hard_splits_long_line():
    parts = split_message("x" * 250, limit=100)
    assert [len(p) for p in parts] == [100, 100, 50]


def test_empty():
    assert split_message("") == [""]
