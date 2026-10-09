from app.llm import extract_json


class FakeLLM:
    def __init__(self, reply="", exc=None):
        self.reply = reply
        self.exc = exc
        self.calls = []

    async def ask(self, prompt, system="", image=None, max_tokens=1024):
        self.calls.append({"prompt": prompt, "system": system, "image": image})
        if self.exc:
            raise self.exc
        return self.reply

    async def ask_json(self, prompt, system="", image=None):
        return extract_json(await self.ask(prompt, system, image))


class FakeDB:
    def __init__(self, schedules=None, notes=None):
        self.schedules = schedules or {}
        self.notes = notes or []

    async def get_schedule(self, kind, day=""):
        return self.schedules.get((kind, day))

    async def all_schedules(self):
        return {
            "okul": self.schedules.get(("okul", "")),
            "cumartesi": self.schedules.get(("dershane", "cumartesi")),
            "pazar": self.schedules.get(("dershane", "pazar")),
        }

    async def recent_notes(self, limit=50):
        return self.notes[:limit]
