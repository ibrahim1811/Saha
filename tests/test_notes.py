from types import SimpleNamespace

import pytest

from app.notes import Transcriber


class _Tr:
    def __init__(self, text):
        self.text = text
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text=self.text)


def _client(text):
    tr = _Tr(text)
    return tr, SimpleNamespace(audio=SimpleNamespace(transcriptions=tr))


async def test_transcribe_turkish():
    tr, client = _client("  süt almayı unutma ")
    assert await Transcriber("k", client=client).transcribe(b"ogg") == "süt almayı unutma"
    assert tr.kwargs["model"] == "whisper-large-v3"
    assert tr.kwargs["language"] == "tr"
    assert tr.kwargs["file"] == ("voice.ogg", b"ogg")


async def test_empty_transcript_raises():
    _, client = _client("   ")
    with pytest.raises(ValueError):
        await Transcriber("k", client=client).transcribe(b"ogg")
