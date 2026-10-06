"""Этап 7: прод отделён от стенда (аудит, раздел 3, задача 1)."""

import os
import tempfile
import unittest
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-prod-")) / "prod.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401
from app.main import _hits, app
from app.store import init_db


class Prod(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.saved = os.environ.get("AMPLUA_ENV")
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        if cls.saved is None:
            os.environ.pop("AMPLUA_ENV", None)
        else:
            os.environ["AMPLUA_ENV"] = cls.saved

    def setUp(self):
        _hits.clear()
        os.environ["AMPLUA_ENV"] = "prod"

    def test_head_me_without_token_is_401_in_contract_format(self):
        head = self.client.head("/v1/me")
        self.assertEqual((head.status_code, head.content), (401, b""))
        self.assertEqual(head.headers["content-type"], "application/json")
        body = self.client.get("/v1/me").json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(set(body["error"]), {"code", "message"})
        self.assertEqual(body["error"]["code"], "unauthorized")

    def test_stand_paths_are_closed_on_prod(self):
        for path in ("/stand", "/docs", "/openapi.json", "/positions", "/users/me", "/puzzles/next", "/leaderboards/global"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.post("/auth/dev-login", json={"name": "x"}).status_code, 404)
        self.assertNotIn("integrations", self.client.get("/health").json())

    def test_site_and_v1_stay_open_on_prod(self):
        for path in ("/", "/privacy", "/terms", "/delete-account", "/l/ABCDEF", "/health", "/assets/site.css"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_stand_paths_open_off_prod(self):
        os.environ["AMPLUA_ENV"] = "stand"
        self.assertEqual(self.client.get("/stand").status_code, 200)
        self.assertIn("integrations", self.client.get("/health").json())


if __name__ == "__main__":
    unittest.main()
