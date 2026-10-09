import base64
import json
import re

import httpx


class LLMError(Exception):
    pass


def extract_json(text: str):
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return decoder.raw_decode(text, i)[0]
            except json.JSONDecodeError:
                continue
    raise LLMError(f"JSON bulunamadı: {text[:200]}")


class LLM:
    def __init__(self, api_key: str, base_url: str, model: str, vision_model: str, http: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.vision_model = vision_model
        self.http = http or httpx.AsyncClient()

    async def ask(self, prompt: str, system: str = "", image: bytes | None = None, max_tokens: int = 1024) -> str:
        if image is None:
            user = prompt
        else:
            data_url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
            user = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_url}}]
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        body = {
            "model": self.vision_model if image is not None else self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        try:
            resp = await self.http.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"LLM API'ye ulaşılamadı: {e!r}") from e
        if resp.status_code != 200:
            raise LLMError(f"LLM API hatası {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"LLM yanıtı beklenmeyen biçimde: {resp.text[:300]}") from e

    async def ask_json(self, prompt: str, system: str = "", image: bytes | None = None):
        return extract_json(await self.ask(prompt, system, image))
