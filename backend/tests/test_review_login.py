"""Вход для ревьюеров по логину и паролю (аудит, раздел 4, вопрос 3, вариант (б) по решению команды)."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-revlogin-")) / "revlogin.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401
import app.v1 as v1
from app import review_login
from app.main import _hits, app
from app.store import connect, init_db
from scripts import seed_reviewer

LOGIN, PASSWORD = "review@amplua.app", "Test-Password-2026"
ENV = {"REVIEW_LOGIN_ENABLED": "true", "REVIEW_LOGIN": LOGIN, "REVIEW_PASSWORD_HASH": review_login.make_hash(PASSWORD, iterations=1000)}


class ReviewLogin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.saved = {name: os.environ.get(name) for name in ENV}
        cls.real_verify = v1.verify_identity
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        v1.verify_identity = cls.real_verify
        for name, value in cls.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def setUp(self):
        _hits.clear()
        os.environ.update(ENV)

    def login(self, login: str = LOGIN, password: str = PASSWORD):
        _hits.pop("review-login:testclient", None)
        return self.client.post("/v1/auth/review", json={"login": login, "password": password})

    def seed(self, *flags: str) -> dict:
        saved = sys.argv
        sys.argv = ["seed_reviewer.py", *flags]
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                seed_reviewer.main()
        finally:
            sys.argv = saved
        text = output.getvalue()
        return json.loads(text[: text.rindex("}") + 1])

    def test_disabled_is_invisible(self):
        for name in ENV:
            os.environ.pop(name)
            for body in ({"login": LOGIN, "password": PASSWORD}, {}):
                response = self.client.post("/v1/auth/review", json=body)
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (404, "not_found"), name)
            os.environ.update(ENV)
        os.environ["REVIEW_LOGIN_ENABLED"] = "false"
        self.assertEqual(self.login().status_code, 404)

    def test_wrong_credentials_and_rate_limit(self):
        for login, password in ((LOGIN, "wrong-password"), ("other@amplua.app", PASSWORD), ("", "")):
            response = self.login(login, password)
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (401, "unauthorized"))
        _hits.clear()
        codes = [self.client.post("/v1/auth/review", json={"login": LOGIN, "password": "nope"}).status_code for _ in range(6)]
        self.assertEqual(codes, [401] * 5 + [429])

    def test_seeded_account_unbound_from_gmail(self):
        with connect() as connection:
            connection.execute("DELETE FROM users WHERE sub = ?", (review_login.REVIEW_SUB,))
        gmail = f"{uuid.uuid4().hex}@gmail.com"
        first = self.seed("--email", gmail)
        summary = self.seed("--password-login", "--email", gmail)
        self.assertEqual(summary["userId"], first["userId"])
        self.assertEqual((summary["email"], summary["sessionsCount"]), ("review@amplua.app", first["sessionsCount"]))

        response = self.login()
        self.assertEqual(response.status_code, 200, response.text)
        me = response.json()["user"]
        self.assertEqual((me["id"], me["position"], me["streak"]), (summary["userId"], "dm", 5))
        headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}
        self.assertEqual(len(self.client.get("/v1/leagues", headers=headers).json()), 2)

        # Вход через Google с прежним Gmail к этому аккаунту больше не привязывается.
        v1.verify_identity = lambda provider, token: {"sub": "123456789", "email": gmail, "email_verified": True}
        google = self.client.post("/v1/auth/google", json={"idToken": "x"}).json()
        self.assertNotEqual(google["user"]["id"], summary["userId"])

    def test_deleted_account_comes_back_empty(self):
        response = self.login()
        headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}
        old_id = response.json()["user"]["id"]
        self.assertEqual(self.client.delete("/v1/me", headers=headers).status_code, 204)
        again = self.login().json()["user"]
        self.assertNotEqual(again["id"], old_id)
        self.assertEqual((again["elo"], again["position"]), (800, None))
        with connect() as connection:
            self.assertEqual(connection.execute("SELECT review FROM users WHERE id = ?", (again["id"],)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
