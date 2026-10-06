"""Этап 6: скрипт аккаунта ревьюера и привязка к тестовой Google-учётке (аудит, раздел 3, задача 4)."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-review-")) / "review.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401
import app.v1 as v1
from app.main import _hits, app
from app.store import connect, init_db
from scripts import seed_reviewer

EMAIL = "amplua.review@gmail.com"


class Reviewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.real_verify = v1.verify_identity
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        v1.verify_identity = cls.real_verify

    def seed(self, *flags: str) -> dict:
        saved = sys.argv
        sys.argv = ["seed_reviewer.py", "--email", EMAIL, *flags]
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                seed_reviewer.main()
        finally:
            sys.argv = saved
        text = output.getvalue()
        return json.loads(text[: text.rindex("}") + 1])

    def google(self, sub: str, email: str, verified: bool = True) -> dict:
        _hits.clear()
        v1.verify_identity = lambda provider, token: {"sub": sub, "email": email, "email_verified": verified}
        response = self.client.post("/v1/auth/google", json={"idToken": "x"})
        self.assertEqual(response.status_code, 200, response.text)
        who = response.json()
        who["headers"] = {"Authorization": f"Bearer {who['accessToken']}", "X-Timezone-Offset": "180"}
        return who

    def test_seed_bind_and_reseed(self):
        summary = self.seed()
        self.assertFalse(summary["boundToGoogle"])
        self.assertGreaterEqual(summary["sessionsCount"], 20)
        self.assertEqual(summary["streak"], 5)
        self.assertEqual((summary["isPro"], summary["aiConsentAt"]), (False, None))
        self.assertEqual(sorted(item["members"] for item in summary["leagues"]), [5, 5])

        # Первый вход тестовой учёткой: заготовка привязывается, ревьюер видит заполненный профиль.
        who = self.google("google-sub-reviewer", EMAIL.upper())
        me = who["user"]
        self.assertEqual(me["id"], summary["userId"])
        self.assertEqual((me["position"], me["name"], me["streak"]), ("dm", "Ревьюер Amplua", 5))
        self.assertNotEqual(me["elo"], 800)
        self.assertEqual(len(set(me["eloHistory"])) > 1, True)
        modes = {item["mode"] for item in self.client.get("/v1/me/attempts?limit=100", headers=who["headers"]).json()["items"]}
        self.assertEqual(modes, {"polygon", "rush", "video"})
        leagues = self.client.get("/v1/leagues", headers=who["headers"]).json()
        self.assertEqual(len(leagues), 2)
        board = self.client.get(f"/v1/leagues/{leagues[0]['id']}/leaderboard", headers=who["headers"]).json()
        self.assertEqual(board["total"], 5)
        # Служебные игроки не видны в общей таблице.
        world = self.client.get("/v1/leaderboards/global", headers=who["headers"]).json()
        bot_ids = {player["id"] for player in board["players"]} - {me["id"]}
        self.assertFalse(bot_ids & {player["id"] for player in world["players"]})

        # Повторный запуск пересоздаёт прогресс, служебные игроки не множатся, PRO по флагу.
        again = self.seed("--pro")
        self.assertEqual((again["userId"], again["boundToGoogle"], again["isPro"]), (summary["userId"], True, True))
        self.assertEqual(again["sessionsCount"], summary["sessionsCount"])
        with connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users WHERE review_bot = 1").fetchone()[0], 8)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM leagues WHERE owner_id = ?", (summary["userId"],)).fetchone()[0], 2)

    def test_binding_needs_verified_email_and_review_flag(self):
        email = f"{uuid.uuid4().hex}@gmail.com"
        with connect() as connection:
            connection.execute(
                "INSERT INTO users (id, name, provider, sub, email, review) VALUES (?, ?, 'google', NULL, ?, 0)",
                (uuid.uuid4().hex, f"plain:{email}", email),
            )
        # Строка без флага review не привязывается к чужому входу.
        stranger = self.google(f"sub-{uuid.uuid4().hex}", email)
        with connect() as connection:
            row = connection.execute("SELECT review, sub FROM users WHERE email = ? AND sub IS NULL", (email,)).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(stranger["user"]["email"], None)

        with connect() as connection:
            connection.execute("UPDATE users SET review = 1 WHERE email = ? AND sub IS NULL", (email,))
        # Неподтверждённый email не привязывает.
        unverified = self.google(f"sub-{uuid.uuid4().hex}", email, verified=False)
        with connect() as connection:
            still = connection.execute("SELECT id FROM users WHERE email = ? AND sub IS NULL AND review = 1", (email,)).fetchone()
        self.assertIsNotNone(still)
        self.assertNotEqual(unverified["user"]["id"], still["id"])


if __name__ == "__main__":
    unittest.main()
