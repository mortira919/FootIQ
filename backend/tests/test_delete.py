"""Этап 1: DELETE /v1/me целиком и вход через Apple (аудит, раздел 3, задачи 2 и 8)."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-delete-")) / "delete.sqlite"

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

import app.main  # noqa: F401  (точка входа: main подключает v1)
import app.v1 as v1
from app.main import _hits, app
from app.store import connect, init_db
from tests.mock_http import MockServer

BUNDLE, TEAM, KEY_ID = "com.amplua.amplua", "TEAM123456", "KEY1234567"


def fake_identity(provider: str, token: str) -> dict:
    # Токен в тестах: "<sub>|<email>"; подпись провайдера проверяется в verify_identity и здесь не нужна.
    sub, _, email = token.partition("|")
    return {"sub": sub, "email": email or None}


class DeleteAndApple(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.key = ec.generate_private_key(ec.SECP256R1())
        pem = cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.mock = MockServer()
        cls.mock.routes[("POST", "/auth/token")] = lambda request: (200, {"refresh_token": "rt-" + request["body"]["code"], "token_type": "Bearer"})
        cls.mock.routes[("POST", "/auth/revoke")] = (200, None)
        cls.mock.routes[("DELETE", "/v1/subscribers/")] = (200, {})
        cls.env = {
            "APPLE_AUTH_URL": cls.mock.url,
            "APPLE_TEAM_ID": TEAM,
            "APPLE_KEY_ID": KEY_ID,
            "APPLE_PRIVATE_KEY": pem.decode(),
            "APPLE_BUNDLE_ID": BUNDLE,
            "REVENUECAT_API_URL": cls.mock.url + "/v1",
            "REVENUECAT_SECRET_KEY": "sk_test_amplua",
        }
        cls.saved_env = {name: os.environ.get(name) for name in cls.env}
        os.environ.update(cls.env)
        cls.real_verify = v1.verify_identity
        v1.verify_identity = fake_identity
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        v1.verify_identity = cls.real_verify
        for name, value in cls.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cls.mock.stop()

    def setUp(self):
        _hits.clear()
        self.mock.requests.clear()

    # --- помощники ---

    def headers(self, who: dict) -> dict:
        return {"Authorization": f"Bearer {who['accessToken']}", "X-Timezone-Offset": "180"}

    def google(self, sub: str | None = None) -> dict:
        response = self.client.post("/v1/auth/google", json={"idToken": f"{sub or uuid.uuid4().hex}|g@example.com"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def apple(self, email: str, code: str | None = "code-1", sub: str | None = None) -> dict:
        body = {"identityToken": f"{sub or uuid.uuid4().hex}|{email}", "authorizationCode": code, "givenName": "Артём", "familyName": None}
        response = self.client.post("/v1/auth/apple", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def call(self, method: str, url: str, who: dict, status: int = 200, **kwargs):
        response = self.client.request(method, url, headers=self.headers(who), **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        return response.json() if response.content else None

    def assert_client_secret(self, secret: str):
        claims = jwt.decode(secret, self.key.public_key(), algorithms=["ES256"], audience="https://appleid.apple.com")
        self.assertEqual((claims["iss"], claims["sub"]), (TEAM, BUNDLE))
        self.assertLessEqual(claims["exp"] - claims["iat"], 300)
        self.assertEqual(jwt.get_unverified_header(secret)["kid"], KEY_ID)

    def rows_of(self, user_id: str, league_codes: list[str]) -> dict:
        with connect() as connection:
            count = lambda sql, *args: connection.execute(sql, args).fetchone()[0]  # noqa: E731
            counts = {table: count(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", user_id) for table in store.USER_TABLES}
            counts["users"] = count("SELECT COUNT(*) FROM users WHERE id = ?", user_id)
            counts["reports"] = count("SELECT COUNT(*) FROM reports WHERE reporter_id = ? OR target_id = ? OR target_owner_id = ?", user_id, user_id, user_id)
            counts["blocks"] = count("SELECT COUNT(*) FROM blocks WHERE blocker_id = ? OR blocked_id = ?", user_id, user_id)
            counts["leagues"] = count("SELECT COUNT(*) FROM leagues WHERE owner_id = ?", user_id)
            placeholders = ",".join("?" * len(league_codes))
            counts["owned_league_members"] = count(f"SELECT COUNT(*) FROM league_members WHERE code IN ({placeholders})", *league_codes)
        return counts

    # --- критерии этапа 1 ---

    def test_delete_erases_everything(self):
        doomed = self.google()
        me = doomed["user"]
        uid = me["id"]
        self.call("PATCH", "/v1/me", doomed, json={"position": "dm", "name": "Удаляемый"})

        # Попытки: полигон, задача дня (серия) и видеоразбор с текстом ответа.
        self.call("POST", "/v1/attempts/polygon", doomed, json={"sceneId": "dm", "target": None})
        daily = self.call("GET", "/v1/me", doomed)["daily"]
        self.call("POST", "/v1/attempts/polygon", doomed, json={**daily, "target": None, "daily": True})
        puzzle = self.call("GET", "/v1/puzzles/video", doomed)
        session = self.call("POST", "/v1/modes/video/start", doomed, json={"puzzleId": puzzle["id"]})
        self.call("POST", "/v1/attempts/video", doomed, json={"sessionId": session["sessionId"], "puzzleId": puzzle["id"], "choice": 1, "answer": "открываюсь из тени опеки под пас"})

        # Лига создателя с участником и чужая лига, где удаляемый участник.
        own = self.call("POST", "/v1/leagues", doomed, json={"name": "Моя лига"})
        member = self.google()
        self.call("PATCH", "/v1/me", member, json={"position": "cm"})
        self.call("POST", "/v1/leagues/join", member, json={"code": own["code"]})
        foreign = self.call("POST", "/v1/leagues", member, json={"name": "Чужая лига"})
        self.call("POST", "/v1/leagues/join", doomed, json={"code": foreign["code"]})

        # Кэш, журнал LLM, жалобы и блокировки этого игрока (эндпоинты для них появятся на этапах 2-3).
        with connect() as connection:
            connection.execute("INSERT INTO semantic_cache VALUES ('v_dm', 'dm', 'base', 'k', ?, '{}')", (uid,))
            connection.execute("INSERT INTO llm_log (user_id, provider, status) VALUES (?, 'test', 'ok')", (uid,))
            connection.execute("INSERT INTO reports (id, reporter_id, target_type, target_id, reason) VALUES (?, ?, 'user', ?, 'other')", (uuid.uuid4().hex, uid, member["user"]["id"]))
            connection.execute("INSERT INTO reports (id, reporter_id, target_type, target_id, reason) VALUES (?, ?, 'user', ?, 'other')", (uuid.uuid4().hex, member["user"]["id"], uid))
            connection.execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (uid, member["user"]["id"]))

        before = self.rows_of(uid, [own["code"]])
        for table in ("users", "attempts", "league_members", "sessions", "refresh_tokens", "semantic_cache", "llm_log", "reports", "blocks", "leagues", "owned_league_members"):
            self.assertGreater(before[table], 0, table)

        self.call("DELETE", "/v1/me", doomed, 204)

        # 1. Тот же токен больше не работает.
        response = self.client.get("/v1/me", headers=self.headers(doomed))
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (401, "unauthorized"))
        refresh = self.client.post("/v1/auth/refresh", json={"refreshToken": doomed["refreshToken"]})
        self.assertEqual(refresh.status_code, 401)

        # 2. Никаких записей игрока в базе.
        self.assertEqual(set(self.rows_of(uid, [own["code"]]).values()), {0})

        # 3. Участник удалённой лиги её больше не видит, а своя лига у него осталась без удалённого игрока.
        leagues = self.call("GET", "/v1/leagues", member)
        self.assertEqual([league["id"] for league in leagues], [foreign["code"]])
        self.assertEqual(leagues[0]["membersCount"], 1)
        joined = self.client.post("/v1/leagues/join", headers=self.headers(member), json={"code": own["code"]})
        self.assertEqual((joined.status_code, joined.json()["error"]["code"]), (404, "league_not_found"))

        # RevenueCat получил удаление подписчика с секретным ключом.
        deletes = self.mock.calls("DELETE", f"/v1/subscribers/{uid}")
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0]["headers"]["Authorization"], "Bearer sk_test_amplua")

    def test_apple_revoke_on_delete(self):
        who = self.apple("x@private.icloud.com", code="code-revoke")
        exchange = self.mock.calls("POST", "/auth/token")[-1]["body"]
        self.assertEqual((exchange["code"], exchange["grant_type"], exchange["client_id"]), ("code-revoke", "authorization_code", BUNDLE))
        self.assert_client_secret(exchange["client_secret"])
        with connect() as connection:
            stored = connection.execute("SELECT apple_refresh FROM users WHERE id = ?", (who["user"]["id"],)).fetchone()[0]
        self.assertEqual(stored, "rt-code-revoke")

        self.call("DELETE", "/v1/me", who, 204)

        # 4. Мок appleid.apple.com получил POST /auth/revoke с сохранённым токеном.
        revokes = self.mock.calls("POST", "/auth/revoke")
        self.assertEqual(len(revokes), 1)
        body = revokes[0]["body"]
        self.assertEqual((body["token"], body["token_type_hint"], body["client_id"]), ("rt-code-revoke", "refresh_token", BUNDLE))
        self.assert_client_secret(body["client_secret"])

    def test_relogin_after_delete_starts_from_scratch(self):
        sub = uuid.uuid4().hex
        first = self.google(sub)
        self.call("PATCH", "/v1/me", first, json={"position": "cm"})
        self.call("POST", "/v1/attempts/polygon", first, json={"sceneId": "cm", "target": None})
        self.call("DELETE", "/v1/me", first, 204)

        # 5. Тот же Google sub создаёт нового игрока с ELO 800.
        second = self.google(sub)
        me = second["user"]
        self.assertNotEqual(me["id"], first["user"]["id"])
        self.assertEqual((me["elo"], me["position"], me["sessionsCount"], me["streak"]), (800, None, 0, 0))

    def test_apple_private_relay_emails(self):
        # 6. Адреса private.icloud.com и privaterelay.appleid.com проходят без белого списка доменов.
        for email in ("x@private.icloud.com", "abc123@privaterelay.appleid.com", "player@icloud.com"):
            who = self.apple(email)
            self.assertEqual((who["user"]["email"], who["user"]["provider"]), (email, "apple"))

        # Apple отдаёт email только при первом входе: повторный вход без email его не стирает.
        sub = uuid.uuid4().hex
        self.apple("first@private.icloud.com", sub=sub)
        again = self.client.post("/v1/auth/apple", json={"identityToken": f"{sub}|", "authorizationCode": None})
        self.assertEqual(again.json()["user"]["email"], "first@private.icloud.com")

    def test_delete_survives_apple_and_revenuecat_failures(self):
        who = self.apple("y@private.icloud.com", code="code-fail")
        self.mock.routes[("POST", "/auth/revoke")] = (500, {"error": "server_error"})
        self.mock.routes[("DELETE", "/v1/subscribers/")] = (503, {"message": "down"})
        try:
            self.call("DELETE", "/v1/me", who, 204)
        finally:
            self.mock.routes[("POST", "/auth/revoke")] = (200, None)
            self.mock.routes[("DELETE", "/v1/subscribers/")] = (200, {})
        self.assertEqual(self.client.get("/v1/me", headers=self.headers(who)).status_code, 401)
        with connect() as connection:
            self.assertIsNone(connection.execute("SELECT id FROM users WHERE id = ?", (who["user"]["id"],)).fetchone())

    def test_apple_login_works_without_key(self):
        saved = os.environ.pop("APPLE_PRIVATE_KEY")
        try:
            who = self.apple("z@private.icloud.com", code="code-nokey")
            self.assertEqual(self.mock.calls("POST", "/auth/token"), [])
            self.call("DELETE", "/v1/me", who, 204)
            self.assertEqual(self.mock.calls("POST", "/auth/revoke"), [])
        finally:
            os.environ["APPLE_PRIVATE_KEY"] = saved


if __name__ == "__main__":
    unittest.main()
