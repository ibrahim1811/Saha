from groq import AsyncGroq

MODEL = "whisper-large-v3"


class Transcriber:
    def __init__(self, api_key: str, client=None):
        self.client = client or AsyncGroq(api_key=api_key, timeout=30)

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        resp = await self.client.audio.transcriptions.create(file=(filename, audio), model=MODEL, language="tr")
        text = resp.text.strip()
        if not text:
            raise ValueError("Ses boş ya da anlaşılamadı")
        return text
