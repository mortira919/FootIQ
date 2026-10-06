"""Этап 5: удаление аккаунта через веб по ссылке из письма (аудит, раздел 3, задача 3)."""

import re
import tempfile
import unittest
import uuid
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-webdel-")) / "webdel.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401
import app.v1 as v1
from app import mailer
from app.main import _hits, app
from app.store import connect, init_db


def fake_identity(provider: str, token: str) -> dict:
    return {"sub": token, "email": f"{token}@Mail.example"}


class WebDelete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.real_verify, cls.real_deliver = v1.verify_identity, mailer.deliver
        v1.verify_identity = fake_identity
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        v1.verify_identity, mailer.deliver = cls.real_verify, cls.real_deliver

    def setUp(self):
        _hits.clear()
        self.mail = []
        mailer.deliver = self.mail.append

    def player(self) -> dict:
        sub = uuid.uuid4().hex
        who = self.client.post("/v1/auth/google", json={"idToken": sub}).json()
        who["headers"] = {"Authorization": f"Bearer {who['accessToken']}"}
        self.client.patch("/v1/me", headers=who["headers"], json={"position": "cm"})
        return who

    def request(self, email: str):
        return self.client.post("/delete-account", content=f"email={email}", headers={"Content-Type": "application/x-www-form-urlencoded"})

    def token_from_mail(self) -> str:
        self.assertEqual(len(self.mail), 1)
        body = self.mail[0].get_content()
        match = re.search(r"/delete-account/confirm\?token=([A-Za-z0-9_\-]+)", body)
        self.assertIsNotNone(match, body)
        return match.group(1)

    def confirm(self, token: str):
        return self.client.post("/delete-account/confirm", content=f"token={token}", headers={"Content-Type": "application/x-www-form-urlencoded"})

    def test_form_mail_link_deletes_like_api(self):
        who = self.player()
        uid = who["user"]["id"]
        self.client.post("/v1/attempts/polygon", headers=who["headers"], json={"sceneId": "cm", "target": None})
        league = self.client.post("/v1/leagues", headers=who["headers"], json={"name": "Веб-лига"}).json()

        page = self.client.get("/delete-account")
        self.assertEqual(page.status_code, 200)
        self.assertIn('action="/delete-account"', page.text)
        self.assertIn("Что удаляется", page.text)
        self.assertIn("24 часа", page.text)

        # Регистр адреса не важен.
        sent = self.request(who["user"]["email"].upper())
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(self.mail[0]["To"], who["user"]["email"].upper())
        self.assertEqual(self.mail[0]["Subject"], "Удаление аккаунта Amplua")
        token = self.token_from_mail()

        # Ссылка из письма сама ничего не удаляет: только показывает кнопку подтверждения.
        landing = self.client.get(f"/delete-account/confirm?token={token}")
        self.assertEqual(landing.status_code, 200)
        self.assertIn("Удалить навсегда", landing.text)
        self.assertEqual(self.client.get("/v1/me", headers=who["headers"]).status_code, 200)

        done = self.confirm(token)
        self.assertEqual(done.status_code, 200)
        self.assertIn("Аккаунт удалён", done.text)

        # Как после DELETE /v1/me: токен не работает, данных игрока нет, лига исчезла.
        self.assertEqual(self.client.get("/v1/me", headers=who["headers"]).status_code, 401)
        with connect() as connection:
            for table in store.USER_TABLES:
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,)).fetchone()[0], 0, table)
            self.assertIsNone(connection.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone())
            self.assertIsNone(connection.execute("SELECT code FROM leagues WHERE code = ?", (league["code"],)).fetchone())

        # Ссылка одноразовая.
        self.assertEqual(self.confirm(token).status_code, 410)
        self.assertEqual(self.client.get(f"/delete-account/confirm?token={token}").status_code, 410)

    def test_unknown_email_gets_the_same_answer(self):
        known = self.player()
        on_known = self.request(known["user"]["email"])
        self.assertEqual(len(self.mail), 1)
        self.mail.clear()
        on_unknown = self.request(f"{uuid.uuid4().hex}@mail.example")
        self.assertEqual(self.mail, [])
        self.assertEqual((on_unknown.status_code, on_unknown.text), (on_known.status_code, on_known.text))

    def test_expired_and_forged_links(self):
        who = self.player()
        self.request(who["user"]["email"])
        token = self.token_from_mail()
        with connect() as connection:
            connection.execute("UPDATE deletion_requests SET created_at = datetime('now', '-25 hours')")
        self.assertEqual(self.client.get(f"/delete-account/confirm?token={token}").status_code, 410)
        self.assertEqual(self.confirm(token).status_code, 410)
        self.assertEqual(self.confirm("forged-token").status_code, 410)
        self.assertEqual(self.confirm("").status_code, 410)
        self.assertEqual(self.client.get("/v1/me", headers=who["headers"]).status_code, 200)
        with connect() as connection:
            stored = [row[0] for row in connection.execute("SELECT token_hash FROM deletion_requests")]
        self.assertNotIn(token, stored)

    def test_bad_input_rate_limit_and_old_address(self):
        self.assertEqual(self.request("not-an-email").status_code, 400)
        email = f"{uuid.uuid4().hex}@mail.example"
        self.assertEqual([self.request(email).status_code for _ in range(3)], [200, 200, 429])
        old = self.client.get("/delete", follow_redirects=False)
        self.assertEqual((old.status_code, old.headers["location"]), (308, "/delete-account"))


if __name__ == "__main__":
    unittest.main()
