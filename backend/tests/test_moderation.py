"""Этап 2: модерация UGC, жалобы, блокировки, исключение из лиги и админка (аудит, раздел 3, задача 6)."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-moderation-")) / "moderation.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401
import app.v1 as v1
from app.main import _hits, app
from app.moderation import is_harmful, is_offensive
from app.store import connect, init_db
from tests.mock_http import MockServer

# Мат и оскорбления: кириллица, латиница вместо кириллицы, цифры, пробелы и точки между буквами, повторы букв.
BAD_NAMES = ["хуй", "xyй", "х у й", "х.у.й", "хуууууй", "пиzда", "6ля", "п1зд@", "ёбаный", "FUUUCK", "blyad", "Сука", "пи-дор"]
# Обычные слова, в которые входят похожие буквосочетания: не должны отклоняться.
GOOD_NAMES = ["Артём", "Себастьян", "Тебе", "Небо", "Корабль", "Рубля", "Педро", "Мудрый", "Хулиган", "Глеб", "Застраховать", "Мандарин", "Игрок 4821"]


def fake_identity(provider: str, token: str) -> dict:
    return {"sub": token, "email": f"{token}@example.com"}


class Moderation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.mock = MockServer()
        cls.mock.routes[("POST", "/bot")] = (200, {"ok": True})
        cls.env = {"ADMIN_TOKEN": "admin-secret", "TELEGRAM_API_URL": cls.mock.url, "TELEGRAM_BOT_TOKEN": "bot-token", "TELEGRAM_CHAT_ID": "42"}
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

    def login(self) -> dict:
        response = self.client.post("/v1/auth/google", json={"idToken": uuid.uuid4().hex})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        body["headers"] = {"Authorization": f"Bearer {body['accessToken']}", "X-Timezone-Offset": "180"}
        return body

    def player(self, position: str = "cm", elo: float | None = None, region: str | None = None) -> dict:
        who = self.login()
        patch = {"position": position, **({"region": region} if region else {})}
        self.call("PATCH", "/v1/me", who, json=patch)
        if elo is not None:
            with connect() as connection:
                connection.execute("UPDATE users SET overall_elo = ? WHERE id = ?", (elo, who["user"]["id"]))
        return who

    def call(self, method: str, url: str, who: dict, status: int = 200, **kwargs):
        response = self.client.request(method, url, headers=who["headers"], **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        return response.json() if response.content else None

    def error(self, method: str, url: str, who: dict, status: int, **kwargs) -> dict:
        return self.call(method, url, who, status, **kwargs)["error"]

    def admin(self, method: str, url: str, status: int = 200, **kwargs):
        response = self.client.request(method, url, headers={"Authorization": "Bearer admin-secret"}, **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def ids(self, table: dict) -> list[str]:
        return [player["id"] for player in table["players"]]

    # --- 1. фильтр имён и названий ---

    def test_names_filter(self):
        who = self.player()
        me = self.call("PATCH", "/v1/me", who, json={"name": "Артём"})
        self.assertEqual(me["name"], "Артём")
        for name in BAD_NAMES:
            error = self.error("PATCH", "/v1/me", who, 400, json={"name": name})
            self.assertEqual(error["code"], "validation_error", name)
            self.assertEqual(error["message"], "В имени есть недопустимые слова. Выбери другое")
        self.assertEqual(self.call("GET", "/v1/me", who)["name"], "Артём")

        league = self.call("POST", "/v1/leagues", who, json={"name": "Пятничный футбол"})
        for name in ("Лига мудаков", "сборная xуесосов", "b l y a d"):
            error = self.error("POST", "/v1/leagues", who, 400, json={"name": name})
            self.assertEqual((error["code"], error["message"]), ("validation_error", "В названии лиги есть недопустимые слова. Выбери другое"))
            self.assertEqual(self.error("PATCH", f"/v1/leagues/{league['id']}", who, 400, json={"name": name})["code"], "validation_error")

    def test_filter_has_no_false_positives(self):
        for name in BAD_NAMES:
            self.assertTrue(is_offensive(name), name)
        for name in GOOD_NAMES:
            self.assertFalse(is_offensive(name), name)
        self.assertTrue(is_harmful("убей себя"))
        self.assertFalse(is_harmful("Опорный держит центр, отдай пас на ход правому защитнику"))

    def test_apple_name_is_filtered(self):
        real = v1.verify_identity
        v1.verify_identity = lambda provider, token: {"sub": token, "email": None}
        try:
            body = {"identityToken": uuid.uuid4().hex, "givenName": "Хуй", "familyName": "Пиздец"}
            response = self.client.post("/v1/auth/apple", json=body)
        finally:
            v1.verify_identity = real
        self.assertRegex(response.json()["user"]["name"], r"^Игрок \d{4}$")

    # --- 2. жалобы ---

    def test_reports(self):
        author, target = self.player(), self.player()
        body = {"targetType": "user", "targetId": target["user"]["id"], "reason": "offensive_name", "comment": "Оскорбительное имя"}
        self.call("POST", "/v1/reports", author, 204, json=body)
        self.call("POST", "/v1/reports", author, 204, json=body)
        with connect() as connection:
            rows = connection.execute("SELECT * FROM reports WHERE reporter_id = ?", (author["user"]["id"],)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["status"], rows[0]["target_owner_id"]), ("open", target["user"]["id"]))
        # Модераторы получили одно уведомление, без дубля.
        self.assertEqual(len(self.mock.calls("POST", "/botbot-token/sendMessage")), 1)

        missing = self.error("POST", "/v1/reports", author, 404, json={**body, "targetId": uuid.uuid4().hex})
        self.assertEqual(missing["code"], "not_found")
        self.assertEqual(self.error("POST", "/v1/reports", author, 404, json={**body, "targetType": "league", "targetId": "ZZZZZZ"})["code"], "not_found")
        self.assertEqual(self.error("POST", "/v1/reports", author, 400, json={**body, "targetType": "post"})["code"], "validation_error")
        self.assertEqual(self.error("POST", "/v1/reports", author, 400, json={**body, "reason": "dislike"})["code"], "validation_error")
        self.assertEqual(self.error("POST", "/v1/reports", author, 400, json={**body, "targetId": author["user"]["id"]})["code"], "validation_error")

        league = self.call("POST", "/v1/leagues", target, json={"name": "Лига жалоб"})
        self.call("POST", "/v1/reports", author, 204, json={"targetType": "league", "targetId": league["id"], "reason": "offensive_league"})

    # --- 3. блокировки ---

    def test_blocks_hide_player_only_for_blocker(self):
        a = self.player("cm", elo=4900, region="Армения")
        b = self.player("st", elo=5000, region="Армения")
        league = self.call("POST", "/v1/leagues", a, json={"name": "Лига блока"})
        self.call("POST", "/v1/leagues/join", b, json={"code": league["code"]})
        b_id = b["user"]["id"]

        urls = ["/v1/leaderboards/global", "/v1/leaderboards/regional?region=Армения", f"/v1/leagues/{league['id']}/leaderboard"]
        b_before = [self.call("GET", url, b) for url in urls]
        for url in urls:
            self.assertIn(b_id, self.ids(self.call("GET", url, a)), url)

        self.call("POST", "/v1/blocks", a, 204, json={"userId": b_id})
        self.call("POST", "/v1/blocks", a, 204, json={"userId": b_id})
        blocked = self.call("GET", "/v1/blocks", a)
        self.assertEqual([item["id"] for item in blocked], [b_id])

        for url in urls:
            table = self.call("GET", url, a)
            self.assertNotIn(b_id, self.ids(table), url)
            # Ранги не сдвигаются: у A по-прежнему второе место за скрытым B.
            self.assertEqual(table["me"]["rank"], 2, url)
        # У самого B ничего не меняется.
        self.assertEqual([self.call("GET", url, b) for url in urls], b_before)

        self.assertEqual(self.error("POST", "/v1/blocks", a, 400, json={"userId": a["user"]["id"]})["code"], "validation_error")
        self.assertEqual(self.error("POST", "/v1/blocks", a, 404, json={"userId": uuid.uuid4().hex})["code"], "not_found")

        self.call("DELETE", f"/v1/blocks/{b_id}", a, 204)
        self.assertEqual(self.call("GET", "/v1/blocks", a), [])
        self.assertIn(b_id, self.ids(self.call("GET", urls[0], a)))

    # --- 4. исключение из лиги ---

    def test_kick_member(self):
        owner, member, other = self.player(), self.player(), self.player()
        league = self.call("POST", "/v1/leagues", owner, json={"name": "Лига исключений"})
        for who in (member, other):
            self.call("POST", "/v1/leagues/join", who, json={"code": league["code"]})
        url = f"/v1/leagues/{league['id']}/members/{member['user']['id']}"

        self.assertEqual(self.error("DELETE", url, other, 403)["code"], "not_league_owner")
        self.assertEqual(self.error("DELETE", url, member, 403)["code"], "not_league_owner")
        self_kick = self.error("DELETE", f"/v1/leagues/{league['id']}/members/{owner['user']['id']}", owner, 400)
        self.assertEqual(self_kick["code"], "validation_error")

        self.call("DELETE", url, owner, 204)
        self.assertEqual(self.call("GET", "/v1/leagues", member), [])
        self.assertEqual(self.call("GET", "/v1/leagues", owner)[0]["membersCount"], 2)
        self.assertEqual(self.error("DELETE", url, owner, 404)["code"], "not_found")
        # Исключённый может вернуться только по коду заново, как любой другой игрок.
        self.call("POST", "/v1/leagues/join", member, json={"code": league["code"]})

    # --- админка ---

    def test_admin_queue_and_actions(self):
        self.assertEqual(self.client.get("/admin/reports").status_code, 401)
        self.assertEqual(self.client.get("/admin/reports", headers={"Authorization": "Bearer wrong"}).status_code, 401)

        author, offender = self.player(), self.player(elo=6000)
        self.call("PATCH", "/v1/me", offender, json={"name": "Нормальное имя"})
        offender_id = offender["user"]["id"]
        self.call("POST", "/v1/reports", author, 204, json={"targetType": "user", "targetId": offender_id, "reason": "offensive_name"})

        queue = self.admin("GET", "/admin/reports")
        item = next(item for item in queue["items"] if item["targetId"] == offender_id)
        self.assertEqual((item["snapshot"], item["status"], item["overdue"]), ("Нормальное имя", "open", False))

        reset = self.admin("POST", f"/admin/users/{offender_id}/reset-name")
        self.assertRegex(reset["name"], r"^Игрок \d{4}$")
        self.assertEqual(reset["reportsResolved"], 1)
        self.assertNotIn(offender_id, [item["targetId"] for item in self.admin("GET", "/admin/reports")["items"]])

        # Бан: сессии сброшены, после входа доступно только удаление аккаунта, из таблиц игрок пропал.
        self.admin("POST", f"/admin/users/{offender_id}/ban", json={"reason": "оскорбления"})
        self.assertEqual(self.error("GET", "/v1/me", offender, 401)["code"], "unauthorized")
        again = self.client.post("/v1/auth/google", json={"idToken": offender["user"]["email"].split("@")[0]}).json()
        again["headers"] = {"Authorization": f"Bearer {again['accessToken']}"}
        self.assertEqual(self.error("GET", "/v1/me", again, 403)["code"], "account_banned")
        self.assertNotIn(offender_id, self.ids(self.call("GET", "/v1/leaderboards/global", author)))
        self.admin("POST", f"/admin/users/{offender_id}/unban")
        self.call("GET", "/v1/me", again)

        self.admin("POST", f"/admin/users/{offender_id}/ban", json={"reason": "повтор"})
        relogin = self.client.post("/v1/auth/google", json={"idToken": offender["user"]["email"].split("@")[0]}).json()
        relogin["headers"] = {"Authorization": f"Bearer {relogin['accessToken']}"}
        self.call("DELETE", "/v1/me", relogin, 204)

        # Лиги: переименовать и удалить у всех.
        owner, member = self.player(), self.player()
        league = self.call("POST", "/v1/leagues", owner, json={"name": "Плохая лига"})
        self.call("POST", "/v1/leagues/join", member, json={"code": league["code"]})
        self.call("POST", "/v1/reports", member, 204, json={"targetType": "league", "targetId": league["id"], "reason": "offensive_league"})
        renamed = self.admin("PATCH", f"/admin/leagues/{league['id']}", json={"name": "Лига"})
        self.assertEqual(renamed["reportsResolved"], 1)
        self.assertEqual(self.call("GET", "/v1/leagues", member)[0]["name"], "Лига")
        self.admin("DELETE", f"/admin/leagues/{league['id']}")
        self.assertEqual(self.call("GET", "/v1/leagues", member), [])

        with connect() as connection:
            actions = [row[0] for row in connection.execute("SELECT action FROM admin_log")]
        self.assertTrue({"reset_name", "ban", "unban", "rename_league", "delete_league"} <= set(actions))


if __name__ == "__main__":
    unittest.main()
