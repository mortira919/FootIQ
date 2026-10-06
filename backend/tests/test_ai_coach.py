"""Этап 3: ИИ-тренер. Согласие, данные для LLM, фильтр выдачи, кэш, жалоба на разбор (аудит, раздел 3, задача 7)."""

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-ai-")) / "ai.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401
import app.v1 as v1
from app import llm
from app.main import _hits, app
from app.store import connect, init_db

GOOD_REPLY = {
    "score": 9,
    "checklist": [{"ok": True, "text": "Вариант C верный"}, {"ok": True, "text": "Названа тень опеки"}, {"ok": False, "text": "Не сказано про полупространство"}],
    "reply": "Хорошо. Шаг из тени открыл линию паса.",
}
ANSWER = "Опорник выходит из тени опеки в сторону, чтобы открыть линию паса между линиями"


def fake_identity(provider: str, token: str) -> dict:
    return {"sub": token, "email": f"{token}@secret-mail.example"}


class AICoach(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.env = {"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "sk-test"}
        cls.saved_env = {name: os.environ.get(name) for name in cls.env}
        os.environ.update(cls.env)
        cls.real_verify, cls.real_call = v1.verify_identity, llm.call_model
        v1.verify_identity = fake_identity
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        v1.verify_identity, llm.call_model = cls.real_verify, cls.real_call
        for name, value in cls.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def setUp(self):
        _hits.clear()
        self.prompts: list[tuple[str, str]] = []
        self.reply = json.dumps(GOOD_REPLY, ensure_ascii=False)
        llm.call_model = self.fake_model

    def fake_model(self, system: str, user: str) -> str:
        self.prompts.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    # --- помощники ---

    def player(self, consent: bool = True, name: str | None = None) -> dict:
        response = self.client.post("/v1/auth/google", json={"idToken": uuid.uuid4().hex})
        who = response.json()
        who["headers"] = {"Authorization": f"Bearer {who['accessToken']}", "X-Timezone-Offset": "180"}
        patch = {"position": "dm", **({"aiConsent": True} if consent else {}), **({"name": name} if name else {})}
        who["user"] = self.call("PATCH", "/v1/me", who, json=patch)
        return who

    def call(self, method: str, url: str, who: dict, status: int = 200, **kwargs):
        response = self.client.request(method, url, headers=who["headers"], **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        return response.json() if response.content else None

    def answer(self, who: dict, text: str = ANSWER, choice: int = 2) -> dict:
        puzzle = self.call("GET", "/v1/puzzles/video", who)
        start = self.call("POST", "/v1/modes/video/start", who, json={"puzzleId": puzzle["id"]})
        body = {"sessionId": start["sessionId"], "puzzleId": puzzle["id"], "choice": choice, "answer": text}
        return self.call("POST", "/v1/attempts/video", who, json=body)

    def llm_statuses(self, who: dict) -> list[str]:
        with connect() as connection:
            return [row[0] for row in connection.execute("SELECT status FROM llm_log WHERE user_id = ? ORDER BY id", (who["user"]["id"],))]

    # --- 1. согласие ---

    def test_no_consent_no_video_and_no_spent_attempt(self):
        who = self.player(consent=False)
        self.assertIsNone(who["user"]["aiConsentAt"])
        puzzle = self.call("GET", "/v1/puzzles/video", who)
        error = self.call("POST", "/v1/modes/video/start", who, 403, json={"puzzleId": puzzle["id"]})["error"]
        self.assertEqual(error["code"], "ai_consent_required")
        self.assertEqual(self.call("GET", "/v1/me", who)["attemptsLeft"]["video"], 1)

        me = self.call("PATCH", "/v1/me", who, json={"aiConsent": True})
        self.assertRegex(me["aiConsentAt"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
        start = self.call("POST", "/v1/modes/video/start", who, json={"puzzleId": puzzle["id"]})
        self.assertEqual(start["attemptsLeft"], 0)

        # Согласие отозвали после старта: ответ не принимается, попытка возвращается, в LLM ничего не ушло.
        self.assertIsNone(self.call("PATCH", "/v1/me", who, json={"aiConsent": False})["aiConsentAt"])
        body = {"sessionId": start["sessionId"], "puzzleId": puzzle["id"], "choice": 2, "answer": ANSWER}
        self.assertEqual(self.call("POST", "/v1/attempts/video", who, 403, json=body)["error"]["code"], "ai_consent_required")
        self.assertEqual(self.call("GET", "/v1/me", who)["attemptsLeft"]["video"], 1)
        self.assertEqual(self.prompts, [])

    # --- 2. в LLM нет личных данных ---

    def test_llm_gets_no_personal_data(self):
        who = self.player(name="Кирилл Тайный")
        result = self.answer(who)
        self.assertEqual(len(self.prompts), 1)
        sent = "\n".join(self.prompts[0])
        for secret in (who["user"]["email"], who["user"]["email"].split("@")[0], "Кирилл", "Тайный", who["user"]["id"]):
            self.assertNotIn(secret, sent)
        # Ушло ровно то, что нужно: текст ответа, амплуа и задача.
        self.assertIn(ANSWER, sent)
        self.assertIn("опорный полузащитник", sent)
        self.assertIn("Выйди из тени опеки", sent)
        self.assertEqual((result["score"], result["review"]["reply"]), (9, GOOD_REPLY["reply"]))
        self.assertEqual(result["review"]["checklist"], GOOD_REPLY["checklist"])
        self.assertEqual(self.llm_statuses(who), ["ok"])

    # --- 3. оскорбительный ответ LLM не доходит до игрока ---

    def test_offensive_llm_output_is_replaced(self):
        who = self.player()
        insult = "Ты дебил, сука, иди убей себя"
        self.reply = json.dumps({**GOOD_REPLY, "reply": insult}, ensure_ascii=False)
        result = self.answer(who, text="Отдаю мяч назад центральному защитнику потому что впереди плотно")
        payload = json.dumps(result, ensure_ascii=False)
        for word in ("дебил", "сука", "убей"):
            self.assertNotIn(word, payload)
        self.assertTrue(result["review"]["reply"])
        self.assertEqual(self.llm_statuses(who), ["filtered"])

        # Опасный совет в checklist тоже не проходит.
        other = self.player()
        self.reply = json.dumps({**GOOD_REPLY, "checklist": [{"ok": True, "text": "Сломай сопернику ногу и покончи с этим"}]}, ensure_ascii=False)
        result = self.answer(other, text="Сдвигаюсь вправо в полупространство, чтобы получить пас лицом к воротам")
        self.assertNotIn("покончи", json.dumps(result, ensure_ascii=False))

    def test_llm_failure_falls_back_to_rubric(self):
        who = self.player()
        self.reply = llm.LLMError("timeout")
        result = self.answer(who, text="Остаюсь на месте и жду, когда мяч придёт сам, так спокойнее")
        self.assertTrue(1 <= result["score"] <= 10)
        self.assertTrue(result["review"]["checklist"])
        self.assertEqual(self.llm_statuses(who), ["error"])

        broken = self.player()
        self.reply = "не JSON, а рассуждение"
        result = self.answer(broken, text="Иду в штрафную на добивание, потому что мяч может отскочить")
        self.assertTrue(result["review"]["reply"])
        self.assertEqual(self.llm_statuses(broken), ["error"])

    # --- 4. кэш не отдаёт чужой текст ---

    def test_cache_never_returns_foreign_answer(self):
        a, b = self.player(), self.player()
        text_a = "Выхожу из тени опеки вправо, чтобы открыть линию паса между линиями!"
        text_b = "выхожу  из тени опеки вправо — чтобы открыть линию паса между линиями"
        first = self.answer(a, text=text_a)
        second = self.answer(b, text=text_b)
        self.assertEqual(len(self.prompts), 1, "второй ответ взят из кэша, LLM не вызывалась")
        self.assertEqual(second["review"]["answer"], text_b)
        self.assertNotIn(text_a, json.dumps(second, ensure_ascii=False))
        self.assertEqual((second["review"]["checklist"], second["review"]["reply"]), (first["review"]["checklist"], first["review"]["reply"]))
        self.assertEqual(self.llm_statuses(b), ["cache"])
        # В кэше нет текста ответа.
        with connect() as connection:
            cached = [row[0] for row in connection.execute("SELECT response FROM semantic_cache")]
        self.assertTrue(cached)
        self.assertFalse(any("Выхожу из тени" in item or "выхожу" in item for item in cached))
        # История игрока B тоже хранит его собственный текст.
        history = self.call("GET", "/v1/me/attempts", b)["items"]
        self.assertEqual(history[0]["review"]["answer"], text_b)

        # Другой вариант ответа: другой ключ кэша, LLM вызывается заново.
        c = self.player()
        self.answer(c, text=text_a, choice=0)
        self.assertEqual(len(self.prompts), 2)

    # --- жалоба на разбор ---

    def test_report_review_only_own(self):
        owner, stranger = self.player(), self.player()
        attempt = self.answer(owner, text="Опускаюсь к своим защитникам, чтобы помочь в обороне")["attempt"]
        self.call("POST", "/v1/reports", owner, 204, json={"targetType": "review", "targetId": attempt["id"], "reason": "harmful_ai", "comment": "Грубый тон"})
        error = self.call("POST", "/v1/reports", stranger, 404, json={"targetType": "review", "targetId": attempt["id"], "reason": "harmful_ai"})["error"]
        self.assertEqual(error["code"], "not_found")
        with connect() as connection:
            row = connection.execute("SELECT * FROM reports WHERE target_id = ?", (attempt["id"],)).fetchone()
        self.assertEqual((row["reporter_id"], row["target_owner_id"], row["snapshot"]), (owner["user"]["id"], owner["user"]["id"], GOOD_REPLY["reply"]))


if __name__ == "__main__":
    unittest.main()
