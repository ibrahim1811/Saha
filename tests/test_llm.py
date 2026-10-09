import json

import httpx
import pytest

from app.llm import LLM, LLMError, extract_json


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert extract_json('İşte:\n```json\n{"a": [1, 2]}\n```\nBu kadar.') == {"a": [1, 2]}


def test_json_with_prose():
    assert extract_json('Tabii! [{"ders": "Mat"}] umarım işine yarar') == [{"ders": "Mat"}]


def test_no_json_raises():
    with pytest.raises(LLMError):
        extract_json("Programı okuyamadım.")


def test_broken_json_raises():
    with pytest.raises(LLMError):
        extract_json('{"a": }')


def _llm(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LLM("key", "https://api.test/v1", "text-model", "vision-model", http=http)


async def test_ask_text_uses_text_model_and_system():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": " merhaba "}}]})

    out = await _llm(handler).ask("selam", system="sys", max_tokens=50)
    assert out == " merhaba "
    assert seen["url"] == "https://api.test/v1/chat/completions"
    assert seen["auth"] == "Bearer key"
    assert seen["body"]["model"] == "text-model"
    assert seen["body"]["max_tokens"] == 50
    assert seen["body"]["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "selam"}]


async def test_ask_json_with_image_uses_vision_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    out = await _llm(handler).ask_json("oku", image=b"\xff\xd8")
    assert out == {"ok": True}
    body = seen["body"]
    assert body["model"] == "vision-model"
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "oku"}
    assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,/9g="


async def test_http_error_raises_llm_error():
    llm = _llm(lambda r: httpx.Response(401, json={"error": {"message": "Invalid API Key"}}))
    with pytest.raises(LLMError, match="401"):
        await llm.ask("x")
