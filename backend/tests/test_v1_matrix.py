"""Широкая проверка /v1 по TEST_PROMPT.md: все роли, кривой ввод, изменения состояния."""

import os
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="footiq-matrix-")) / "matrix.sqlite"

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main  # noqa: F401  (точка входа: main подключает v1)
import app.v1 as v1
from app.geometry import gold_centroid
from app.main import _hits, app
from app.store import connect, init_db, user_row

ROLES = ("gk", "cb", "fb", "dm", "cm", "am", "wm", "winger", "st", "ss")
OURS = {"fb": "rb/lb", "wm": "lm/rm", "winger": "lw/rw"}
GOOGLE_URL = v1.PROVIDERS["google"][1]
APPLE_URL = v1.PROVIDERS["apple"][1]
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
REASONS = ("optimal", "safe", "timeout", "out", "noReceiver", "offside", "cone", "shadow", "marked")
ANSWER = "опорник прикрывает зону и выходит из тени, чтобы открыть линию паса"


class Keys:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


def id_token(sub: str | None, aud="web-client", iss="https://accounts.google.com", ttl=600, key=KEY, **claims) -> str:
    body = {"aud": aud, "iss": iss, "exp": int(time.time()) + ttl, "email": f"{sub}@example.com", **claims}
    if sub is not None:
        body["sub"] = sub
    return jwt.encode(body, key, algorithm="RS256")


def gold(role: str, mirrored: bool = False) -> dict:
    x, y = gold_centroid(v1.SCENES[role])
    return {"x": 68 - x if mirrored else x, "y": y}


def offset_for(local_minutes: int) -> int:
    """Смещение, при котором у игрока сейчас local_minutes от полуночи."""
    now = datetime.now(timezone.utc)
    shift = (local_minutes - (now.hour * 60 + now.minute)) % 1440
    return shift - 1440 if shift > 840 else shift


def sql(query: str, *params):
    with connect() as connection:
        return connection.execute(query, params).fetchall()


class Matrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        os.environ["GOOGLE_CLIENT_ID"] = "web-client"
        os.environ["APPLE_BUNDLE_ID"] = "com.footiq.footiq"
        v1._jwks[GOOGLE_URL] = Keys()
        v1._jwks[APPLE_URL] = Keys()
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        v1._jwks.clear()
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("APPLE_BUNDLE_ID", None)

    def setUp(self):
        _hits.clear()

    # --- помощники ---

    def login(self, sub: str | None = None, offset: str | None = "180") -> dict:
        _hits.clear()
        headers = {} if offset is None else {"X-Timezone-Offset": offset}
        response = self.client.post("/v1/auth/google", json={"idToken": id_token(sub or uuid.uuid4().hex)}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        body["headers"] = {"Authorization": f"Bearer {body['accessToken']}", **headers}
        return body

    def call(self, method: str, url: str, who: dict, status: int = 200, **kwargs):
        headers = {**who["headers"], **kwargs.pop("headers", {})}
        response = self.client.request(method, url, headers=headers, **kwargs)
        self.assertEqual(response.status_code, status, f"{method} {url}: {response.text}")
        return response.json() if response.content else None

    def error(self, method: str, url: str, who: dict, status: int, code: str, **kwargs) -> dict:
        body = self.call(method, url, who, status, **kwargs)
        self.assertEqual(set(body), {"error"}, body)
        self.assertEqual(body["error"]["code"], code, body)
        self.assertIsInstance(body["error"]["message"], str)
        self.assertTrue(body["error"]["message"])
        return body["error"]

    def me(self, who: dict) -> dict:
        return self.call("GET", "/v1/me", who)

    def player(self, role: str = "fb") -> dict:
        who = self.login()
        self.call("PATCH", "/v1/me", who, json={"position": role})
        return who

    def pro(self, who: dict, days: int = 5) -> None:
        sql(
            "UPDATE users SET subscription_tier = 'pro', pro_until = ? WHERE id = ?",
            (date.today() + timedelta(days=days)).isoformat(),
            who["user"]["id"],
        )

    def changed(self, before: dict, after: dict) -> set[str]:
        return {key for key in before if before[key] != after[key]}

    def unchanged_after_error(self, who: dict, method: str, url: str, status: int, code: str, **kwargs) -> None:
        before = self.me(who)
        self.error(method, url, who, status, code, **kwargs)
        self.assertEqual(self.me(who), before, f"{method} {url} поменял Me при ошибке")

    # --- 1. формат ошибок и заголовки ---

    def test_error_envelope_for_every_status(self):
        who = self.player("fb")
        self.error("GET", "/v1/nope", who, 404, "not_found")
        self.error("PUT", "/v1/me", who, 405, "method_not_allowed")
        self.error("POST", "/v1/modes/polygon/start", who, 404, "not_found")
        self.error("POST", "/v1/attempts/polygon", who, 400, "validation_error", content="не json", headers={**who["headers"], "Content-Type": "application/json"})
        self.error("POST", "/v1/attempts/polygon", who, 400, "validation_error", json=[1, 2])
        self.error("POST", "/v1/attempts/polygon", who, 400, "validation_error", json={})
        self.error("POST", "/v1/attempts/polygon", who, 400, "validation_error", json={"sceneId": 5})
        self.assertIn("detail", self.client.get("/users/me").json())
        self.assertIn("detail", self.client.get("/nope").json())

    def test_internal_error_uses_envelope(self):
        who = self.login()
        original = v1.player_stats
        v1.player_stats = lambda user_id: 1 / 0
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/v1/me", headers=who["headers"])
        finally:
            v1.player_stats = original
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal")

    def test_authorization_header_variants(self):
        who = self.login()
        token = who["accessToken"]
        for header in ({}, {"Authorization": "Bearer "}, {"Authorization": f"bearer {token}"}, {"Authorization": token}, {"Authorization": "Bearer nope"}):
            self.error("GET", "/v1/me", {"headers": header}, 401, "unauthorized")
        stand = self.client.post("/auth/dev-login", json={"name": "stand-" + uuid.uuid4().hex[:8]}).json()["access_token"]
        self.error("GET", "/v1/me", {"headers": {"Authorization": f"Bearer {stand}"}}, 401, "unauthorized")
        self.assertEqual(self.client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)
        self.assertEqual(self.client.post("/users/me/tier", headers={"Authorization": f"Bearer {token}"}, json={"tier": "pro"}).status_code, 401)
        takeover = self.client.post("/auth/dev-login", json={"name": f"google:{who['user']['id']}"})
        self.assertEqual(takeover.status_code, 409, takeover.text)

    def test_timezone_offset_header(self):
        who = self.login(offset=None)
        for good in ("180", "-300", "+180", "0", "-720", "840"):
            self.call("GET", "/v1/me", {"headers": {**who["headers"], "X-Timezone-Offset": good}})
            stored = sql("SELECT timezone FROM users WHERE id = ?", who["user"]["id"])[0]["timezone"]
            self.assertEqual(stored, str(int(good)))
        for bad in ("841", "-721", "abc", "1.5", ""):
            self.error("GET", "/v1/me", {"headers": {**who["headers"], "X-Timezone-Offset": bad}}, 400, "validation_error")
        self.assertEqual(sql("SELECT timezone FROM users WHERE id = ?", who["user"]["id"])[0]["timezone"], "840")

    def test_offset_moves_the_day_boundary(self):
        who = self.player("dm")
        self.call("POST", "/v1/modes/rush/start", who)
        self.call("POST", "/v1/modes/rush/start", who)
        puzzle = self.call("GET", "/v1/puzzles/video", who)
        self.call("POST", "/v1/modes/video/start", who, json={"puzzleId": puzzle["id"]})
        hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
        sql("UPDATE attempts SET created_at = ? WHERE user_id = ?", hour_ago, who["user"]["id"])

        noon = {"headers": {**who["headers"], "X-Timezone-Offset": str(offset_for(12 * 60))}}
        self.assertEqual(self.me(noon)["attemptsLeft"], {"polygon": None, "rush": 0, "video": 0})
        self.error("POST", "/v1/modes/rush/start", noon, 403, "limit_reached")

        just_after_midnight = {"headers": {**who["headers"], "X-Timezone-Offset": str(offset_for(30))}}
        self.assertEqual(self.me(just_after_midnight)["attemptsLeft"], {"polygon": None, "rush": 2, "video": 1})
        self.call("POST", "/v1/modes/rush/start", just_after_midnight)

    def test_rate_limits(self):
        who = self.login()
        _hits.clear()
        for _ in range(60):
            self.call("GET", "/v1/me", who)
        self.error("GET", "/v1/me", who, 429, "rate_limited")
        _hits.clear()
        for _ in range(20):
            self.client.post("/v1/auth/refresh", json={"refreshToken": "x"})
        self.assertEqual(self.client.post("/v1/auth/refresh", json={"refreshToken": "x"}).json()["error"]["code"], "rate_limited")

    # --- 2. вход и аккаунт ---

    def test_google_token_checks(self):
        sub = uuid.uuid4().hex
        cases = {
            "чужой aud": id_token(sub, aud="someone-else"),
            "чужой iss": id_token(sub, iss="https://evil.example"),
            "истёк": id_token(sub, ttl=-60),
            "нет sub": id_token(None),
            "чужой ключ": id_token(sub, key=OTHER_KEY),
            "мусор": "not.a.jwt",
            "пусто": "",
        }
        for name, token in cases.items():
            _hits.clear()
            response = self.client.post("/v1/auth/google", json={"idToken": token})
            self.assertEqual(response.status_code, 401, f"{name}: {response.text}")
            self.assertEqual(response.json()["error"]["code"], "unauthorized", name)
        self.assertEqual(sql("SELECT COUNT(*) AS n FROM users WHERE sub = ?", sub)[0]["n"], 0)
        too_long = self.client.post("/v1/auth/google", json={"idToken": "x" * 5000})
        self.assertEqual(too_long.json()["error"]["code"], "validation_error")

        os.environ.pop("GOOGLE_CLIENT_ID")
        try:
            off = self.client.post("/v1/auth/google", json={"idToken": id_token(sub)})
        finally:
            os.environ["GOOGLE_CLIENT_ID"] = "web-client"
        self.assertEqual((off.status_code, off.json()["error"]["code"]), (503, "auth_not_configured"))

    def test_apple_names(self):
        def apple(sub: str, **names):
            _hits.clear()
            token = id_token(sub, aud="com.footiq.footiq", iss="https://appleid.apple.com")
            response = self.client.post("/v1/auth/apple", json={"identityToken": token, "authorizationCode": "code", **names})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["user"]

        sub = uuid.uuid4().hex
        first = apple(sub, givenName=" Артём ", familyName="Иванов")
        self.assertEqual((first["name"], first["provider"]), ("Артём Иванов", "apple"))
        self.assertEqual(apple(sub, givenName="Пётр", familyName=None)["name"], "Артём Иванов")
        self.assertRegex(apple(uuid.uuid4().hex, givenName="А", familyName=None)["name"], r"^Игрок \d{4}$")
        self.assertRegex(apple(uuid.uuid4().hex, givenName="  ", familyName="")["name"], r"^Игрок \d{4}$")
        self.assertRegex(apple(uuid.uuid4().hex, givenName="Ann\nBob", familyName=None)["name"], r"^Игрок \d{4}$")
        self.assertEqual(len(apple(uuid.uuid4().hex, givenName="Абвгдеёжзийклмнопрстуф", familyName="Х")["name"]), 20)
        google = self.login()
        self.assertNotEqual(google["user"]["id"], first["id"])

    def test_refresh_and_logout_edges(self):
        who = self.login()
        self.assertEqual(self.client.post("/v1/auth/refresh", json={"refreshToken": ""}).status_code, 401)
        self.assertEqual(self.client.post("/v1/auth/refresh", json={"refreshToken": "x" * 65}).json()["error"]["code"], "validation_error")
        self.assertEqual(self.client.post("/v1/auth/refresh", json={}).json()["error"]["code"], "validation_error")
        self.assertEqual(self.client.post("/v1/auth/logout", json={"refreshToken": "мусор"}).status_code, 204)
        self.call("GET", "/v1/me", who)
        sql("UPDATE refresh_tokens SET created_at = datetime('now', '-31 days') WHERE user_id = ?", who["user"]["id"])
        self.assertEqual(self.client.post("/v1/auth/refresh", json={"refreshToken": who["refreshToken"]}).status_code, 401)
        sql("UPDATE sessions SET created_at = datetime('now', '-61 minutes') WHERE user_id = ?", who["user"]["id"])
        self.error("GET", "/v1/me", who, 401, "unauthorized")

    def test_delete_account_wipes_everything(self):
        sub = uuid.uuid4().hex
        doomed = self.login(sub)
        self.call("PATCH", "/v1/me", doomed, json={"position": "cm"})
        self.call("POST", "/v1/attempts/polygon", doomed, json={"sceneId": "cm", "target": gold("cm")})
        own = self.call("POST", "/v1/leagues", doomed, json={"name": "Своя"})
        friend = self.player("st")
        foreign = self.call("POST", "/v1/leagues", friend, json={"name": "Чужая"})
        self.call("POST", "/v1/leagues/join", friend, json={"code": own["code"]})
        self.call("POST", "/v1/leagues/join", doomed, json={"code": foreign["code"]})
        user_id = doomed["user"]["id"]

        self.call("DELETE", "/v1/me", doomed, 204)
        self.error("GET", "/v1/me", doomed, 401, "unauthorized")
        self.assertEqual(self.client.post("/v1/auth/refresh", json={"refreshToken": doomed["refreshToken"]}).status_code, 401)
        for table in ("users", "attempts", "sessions", "refresh_tokens", "league_members"):
            column = "id" if table == "users" else "user_id"
            self.assertEqual(sql(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = ?", user_id)[0]["n"], 0, table)
        leagues = self.call("GET", "/v1/leagues", friend)
        self.assertEqual([item["code"] for item in leagues], [foreign["code"]])
        self.assertEqual(leagues[0]["membersCount"], 1)
        self.error("POST", "/v1/leagues/join", friend, 404, "league_not_found", json={"code": own["code"]})
        self.assertNotIn(user_id, [item["id"] for item in self.call("GET", "/v1/leaderboards/global", friend)["players"]])

        again = self.login(sub)
        self.assertNotEqual(again["user"]["id"], user_id)
        self.assertEqual((again["user"]["elo"], again["user"]["position"], again["user"]["sessionsCount"]), (800, None, 0))

    # --- 3–4. Me и PATCH ---

    def test_new_player_me_matches_contract_shape(self):
        me = self.login()["user"]
        expected = {
            "id", "name", "email", "provider", "position", "positionLockDays", "region", "coach", "isPro", "elo",
            "positionElo", "eloHistory", "radar", "streak", "streakWeek", "dailyDone", "daily", "rushBest",
            "attemptsLeft", "sessionsCount",
        }
        self.assertEqual(set(me), expected)
        self.assertEqual(
            {key: me[key] for key in expected - {"id", "name", "email"}},
            {
                "provider": "google", "position": None, "positionLockDays": None, "region": None, "coach": "base",
                "isPro": False, "elo": 800, "positionElo": {}, "eloHistory": [800] * 8, "radar": [None] * 5,
                "streak": 0, "streakWeek": [False] * 7, "dailyDone": False, "daily": None, "rushBest": 0,
                "attemptsLeft": {"polygon": None, "rush": 2, "video": 1}, "sessionsCount": 0,
            },
        )

    def test_patch_name_cases(self):
        who = self.login()
        for bad in ("x", " x ", "   ", "a" * 21, "ab\ncd", "ab\tcd"):
            self.unchanged_after_error(who, "PATCH", "/v1/me", 400, "validation_error", json={"name": bad})
        self.error("PATCH", "/v1/me", who, 400, "validation_error", json={"name": 42})
        self.error("PATCH", "/v1/me", who, 400, "validation_error", json={"name": "a" * 65})
        for good, stored in (("ab", "ab"), ("  Артём  ", "Артём"), ("a" * 20, "a" * 20), ("⚽ Месси", "⚽ Месси")):
            self.assertEqual(self.call("PATCH", "/v1/me", who, json={"name": good})["name"], stored)
        self.assertEqual(self.call("PATCH", "/v1/me", who, json={"name": None})["name"], "⚽ Месси")
        self.assertEqual(self.call("PATCH", "/v1/me", who, json={})["name"], "⚽ Месси")

    def test_patch_region_and_coach_cases(self):
        who = self.login()
        for bad in ("KZ", "россия", "Russia", "", "Россия "):
            self.unchanged_after_error(who, "PATCH", "/v1/me", 400, "validation_error", json={"region": bad})
        for region in v1.REGIONS:
            self.assertEqual(self.call("PATCH", "/v1/me", who, json={"region": region})["region"], region)
        self.assertEqual(self.call("PATCH", "/v1/me", who, json={"coach": "base"})["coach"], "base")
        for coach in ("pep", "jose", "jurgen"):
            self.unchanged_after_error(who, "PATCH", "/v1/me", 403, "pro_required", json={"coach": coach})
        self.unchanged_after_error(who, "PATCH", "/v1/me", 400, "validation_error", json={"coach": "klopp"})
        self.pro(who)
        for coach in ("pep", "jose", "jurgen", "base"):
            self.assertEqual(self.call("PATCH", "/v1/me", who, json={"coach": coach})["coach"], coach)

    def test_patch_position_cases_and_lock(self):
        who = self.login()
        for bad in ("rb/lb", "FB", "", "striker"):
            self.unchanged_after_error(who, "PATCH", "/v1/me", 400, "validation_error", json={"position": bad})
        self.error("PATCH", "/v1/me", who, 400, "validation_error", json={"position": 7})

        first = self.call("PATCH", "/v1/me", who, json={"position": "fb"})
        self.assertIsNone(first["positionLockDays"])
        second = self.call("PATCH", "/v1/me", who, json={"position": "wm"})
        self.assertEqual((second["position"], second["positionLockDays"]), ("wm", 30))
        self.assertEqual(self.call("PATCH", "/v1/me", who, json={"position": "wm"})["positionLockDays"], 30)
        locked = self.error("PATCH", "/v1/me", who, 403, "position_locked", json={"position": "st"})
        self.assertEqual(locked["daysLeft"], 30)

        ten_days_ago = (date.today() - timedelta(days=10)).isoformat()
        sql("UPDATE users SET position_changed_on = ? WHERE id = ?", ten_days_ago, who["user"]["id"])
        self.assertIn(self.me(who)["positionLockDays"], (19, 20, 21))
        sql("UPDATE users SET position_changed_on = ? WHERE id = ?", (date.today() - timedelta(days=31)).isoformat(), who["user"]["id"])
        self.assertIsNone(self.me(who)["positionLockDays"])
        self.assertEqual(self.call("PATCH", "/v1/me", who, json={"position": "winger"})["position"], "winger")

        self.pro(who)
        self.assertIsNone(self.me(who)["positionLockDays"])
        for role in ("st", "gk", "ss"):
            self.assertEqual(self.call("PATCH", "/v1/me", who, json={"position": role})["position"], role)
        sql("UPDATE users SET pro_until = '2000-01-01' WHERE id = ?", who["user"]["id"])
        expired = self.me(who)
        self.assertEqual((expired["isPro"], expired["positionLockDays"]), (False, 30))
        self.error("PATCH", "/v1/me", who, 403, "position_locked", json={"position": "cb"})

    def test_patch_is_atomic(self):
        who = self.player("fb")
        self.call("PATCH", "/v1/me", who, json={"position": "wm"})
        pairs = [
            ({"name": "Новое имя", "region": "KZ"}, 400, "validation_error"),
            ({"name": "Новое имя", "position": "st"}, 403, "position_locked"),
            ({"coach": "klopp", "position": "wm", "name": "Новое имя"}, 400, "validation_error"),
            ({"region": "Россия", "coach": "pep"}, 403, "pro_required"),
        ]
        for body, status, code in pairs:
            self.unchanged_after_error(who, "PATCH", "/v1/me", status, code, json=body)

    # --- 5. все роли ---

    def test_every_role_scene_and_video(self):
        for role in ROLES:
            with self.subTest(role=role):
                who = self.player(role)
                stored = sql("SELECT primary_position FROM users WHERE id = ?", who["user"]["id"])[0]["primary_position"]
                self.assertEqual(stored, OURS.get(role, role))
                me = self.me(who)
                self.assertEqual((me["position"], me["daily"]["sceneId"]), (role, role))
                self.assertEqual(self.me(who)["daily"], me["daily"])

                for mirrored in (False, True):
                    result = self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": role, "mirrored": mirrored, "target": gold(role, mirrored)})
                    self.assertEqual((result["reason"], result["attempt"]["outcome"]), ("optimal", "gold"), mirrored)
                    self.assertEqual(result["attempt"]["position"], role)
                timeout = self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": role, "target": None})
                self.assertEqual((timeout["reason"], timeout["attempt"]["outcome"]), ("timeout", "error"))
                for point in ({"x": -1, "y": 50}, {"x": 30, "y": 200}):
                    self.assertEqual(self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": role, "target": point})["reason"], "out")

                me = self.me(who)
                self.assertEqual(list(me["positionElo"]), [role])
                axis = v1.SCENES[role]["axis"]
                self.assertAlmostEqual(me["radar"][axis], round(2 / 5, 2))
                video = self.client.get("/v1/puzzles/video", headers=who["headers"])
                if role == "dm":
                    self.assertEqual(video.status_code, 200)
                else:
                    self.assertEqual((video.status_code, video.json()["error"]["code"]), (404, "not_found"))

    def test_any_scene_counts_for_current_role(self):
        who = self.player("st")
        result = self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": "gk", "target": gold("gk")})
        self.assertEqual(result["attempt"]["position"], "st")
        self.assertEqual(list(result["me"]["positionElo"]), ["st"])

    # --- 6. полигон и задача дня ---

    def test_polygon_input_cases(self):
        who = self.player("fb")
        self.unchanged_after_error(who, "POST", "/v1/attempts/polygon", 400, "validation_error", json={"sceneId": "zz", "target": None})
        self.unchanged_after_error(who, "POST", "/v1/attempts/polygon", 400, "validation_error", json={"sceneId": "", "target": None})
        self.unchanged_after_error(who, "POST", "/v1/attempts/polygon", 400, "validation_error", json={"sceneId": "f" * 65})
        self.unchanged_after_error(who, "POST", "/v1/attempts/polygon", 400, "validation_error", json={"sceneId": "rb/lb"})
        for weird in ({"mirrored": "true"}, {"mirrored": 1}, {"daily": "yes"}, {"target": {"x": "1", "y": 2}}, {"target": {"x": 1}}, {"target": [1, 2]}):
            self.unchanged_after_error(who, "POST", "/v1/attempts/polygon", 400, "validation_error", json={"sceneId": "fb", **weird})
        for raw in ('{"sceneId":"fb","target":{"x":NaN,"y":1}}', '{"sceneId":"fb","target":{"x":Infinity,"y":1}}'):
            self.unchanged_after_error(who, "POST", "/v1/attempts/polygon", 400, "validation_error", content=raw, headers={**who["headers"], "Content-Type": "application/json"})
        x, y = gold_centroid(v1.SCENES["fb"])
        integer = self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": "fb", "target": {"x": round(x), "y": round(y)}})
        self.assertIn(integer["reason"], REASONS)

        fresh = self.login()
        self.unchanged_after_error(fresh, "POST", "/v1/attempts/polygon", 400, "validation_error", json={"sceneId": "fb", "target": None})

    def test_daily_rules(self):
        who = self.player("cm")
        daily = self.me(who)["daily"]
        other_scene = {"sceneId": "st", "mirrored": daily["mirrored"], "target": None, "daily": True}
        other_side = {"sceneId": "cm", "mirrored": not daily["mirrored"], "target": None, "daily": True}
        for wrong in (other_scene, other_side):
            self.unchanged_after_error(who, "POST", "/v1/attempts/polygon", 400, "validation_error", json=wrong)

        body = {**daily, "target": gold("cm", daily["mirrored"]), "daily": True}
        first = self.call("POST", "/v1/attempts/polygon", who, json=body)
        self.assertEqual((first["me"]["streak"], first["me"]["dailyDone"], first["attempt"]["daily"]), (1, True, True))
        self.assertEqual(first["me"]["streakWeek"], [False] * 6 + [True])
        again = self.call("POST", "/v1/attempts/polygon", who, json=body)
        self.assertEqual(again["me"]["streak"], 1)

        user_id = who["user"]["id"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sql("UPDATE users SET last_daily_on = ?, streak_count = 4 WHERE id = ?", yesterday, user_id)
        sql("UPDATE users SET timezone = '0' WHERE id = ?", user_id)
        utc = {"headers": {**who["headers"], "X-Timezone-Offset": "0"}}
        utc_daily = self.me(utc)
        if utc_daily["dailyDone"]:
            self.skipTest("UTC и сервер в разных датах прямо сейчас")
        self.assertEqual(utc_daily["streak"], 4)
        grown = self.call("POST", "/v1/attempts/polygon", utc, json={**utc_daily["daily"], "target": None, "daily": True})
        self.assertEqual(grown["me"]["streak"], 5)

        sql("UPDATE users SET last_daily_on = ?, streak_count = 9 WHERE id = ?", (date.today() - timedelta(days=3)).isoformat(), user_id)
        self.assertEqual(self.me(utc)["streak"], 0)
        restarted = self.call("POST", "/v1/attempts/polygon", utc, json={**utc_daily["daily"], "target": None, "daily": True})
        self.assertEqual(restarted["me"]["streak"], 1)

    def test_attempt_me_equals_get_me(self):
        who = self.player("am")
        result = self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": "am", "target": gold("am")})
        self.assertEqual(result["me"], self.me(who))
        attempt = result["attempt"]
        self.assertEqual(set(attempt), {"id", "mode", "position", "title", "at", "eloDelta", "axis", "daily", "outcome", "score", "review"})
        self.assertTrue(attempt["at"].endswith("Z"))
        datetime.fromisoformat(attempt["at"])
        self.assertEqual((attempt["score"], attempt["review"]), (None, None))

    # --- 7. Rush ---

    def test_rush_lives_and_scoring(self):
        who = self.player("fb")
        good = {"sceneId": "fb", "target": gold("fb")}
        bad = {"sceneId": "fb", "target": None}

        start = self.call("POST", "/v1/modes/rush/start", who)
        two_errors = self.call("POST", "/v1/attempts/rush", who, json={"sessionId": start["sessionId"], "answers": [bad, bad] + [good] * 5})
        self.assertEqual(two_errors["attempt"]["title"], "Серия 5 из 7")
        self.assertEqual(two_errors["attempt"]["outcome"], "silver")
        self.assertEqual(two_errors["me"]["rushBest"], 5)
        self.assertEqual(two_errors["me"]["radar"][3], round(5 / 7, 2))

        start = self.call("POST", "/v1/modes/rush/start", who)
        three_errors = self.call("POST", "/v1/attempts/rush", who, json={"sessionId": start["sessionId"], "answers": [bad] * 3 + [good] * 4})
        self.assertEqual((three_errors["attempt"]["title"], three_errors["attempt"]["outcome"]), ("Серия 0 из 3", "error"))
        self.assertEqual(three_errors["me"]["rushBest"], 5)
        self.assertLess(three_errors["eloDelta"], 0)

        self.pro(who)
        for _ in range(3):
            self.assertIsNone(self.call("POST", "/v1/modes/rush/start", who)["attemptsLeft"])
        start = self.call("POST", "/v1/modes/rush/start", who)
        perfect = self.call("POST", "/v1/attempts/rush", who, json={"sessionId": start["sessionId"], "answers": [good] * 4})
        self.assertEqual((perfect["attempt"]["outcome"], perfect["me"]["rushBest"]), ("gold", 5))

    def test_rush_input_cases(self):
        who = self.player("fb")
        self.error("POST", "/v1/modes/rush/start", self.login(), 400, "validation_error")
        start = self.call("POST", "/v1/modes/rush/start", who)
        session = start["sessionId"]
        good = {"sceneId": "fb", "target": gold("fb")}
        cases = [
            {"sessionId": session, "answers": []},
            {"sessionId": session, "answers": [good] * 101},
            {"sessionId": session, "answers": [{"sceneId": "zz", "target": None}]},
            {"sessionId": session, "answers": [{**good, "mirrored": "no"}]},
            {"sessionId": "выдуманный", "answers": [good]},
            {"sessionId": session},
            {"answers": [good]},
        ]
        for body in cases:
            self.unchanged_after_error(who, "POST", "/v1/attempts/rush", 400, "validation_error", json=body)
        self.call("POST", "/v1/attempts/rush", who, json={"sessionId": session, "answers": [good]})

        dm = self.player("dm")
        puzzle = self.call("GET", "/v1/puzzles/video", dm)
        video = self.call("POST", "/v1/modes/video/start", dm, json={"puzzleId": puzzle["id"]})
        self.unchanged_after_error(dm, "POST", "/v1/attempts/rush", 400, "validation_error", json={"sessionId": video["sessionId"], "answers": [good]})
        self.unchanged_after_error(dm, "POST", "/v1/attempts/rush", 400, "validation_error", json={"sessionId": session, "answers": [good]})

    def test_rush_parallel_start_and_submit(self):
        who = self.player("fb")
        row = user_row(who["user"]["id"])

        def start(_):
            try:
                return v1.start_mode("rush", None, row)["sessionId"]
            except HTTPException as exc:
                return exc.detail["code"]

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(start, range(5)))
        sessions = [item for item in results if item != "limit_reached"]
        self.assertEqual((len(sessions), results.count("limit_reached")), (2, 3), results)

        body = v1.RushIn(sessionId=sessions[0], answers=[v1.RushAnswer(sceneId="fb", target=v1.Target(**gold("fb")))])
        with ThreadPoolExecutor(max_workers=5) as pool:
            replies = list(pool.map(lambda _: v1.attempt_rush(body, row), range(5)))
        self.assertEqual(len({reply["eloDelta"] for reply in replies}), 1)
        self.assertEqual(len({reply["attempt"]["id"] for reply in replies}), 1)
        self.assertEqual(self.me(who)["elo"], 800 + replies[0]["eloDelta"])

    # --- 8. видео ---

    def test_video_input_cases(self):
        who = self.player("dm")
        puzzle = self.call("GET", "/v1/puzzles/video", who)
        self.assertEqual(set(puzzle), {"id", "position", "sceneId", "title", "videoUrl", "options", "chips"})
        self.assertEqual(len(puzzle["options"]), 3)
        for option in puzzle["options"]:
            self.assertTrue(0 <= option["x"] <= 68 and 0 <= option["y"] <= 105, option)
        self.assertEqual(self.me(who)["attemptsLeft"]["video"], 1)

        for body in (None, {}, {"puzzleId": "nope"}, {"puzzleId": 5}):
            kwargs = {} if body is None else {"json": body}
            self.unchanged_after_error(who, "POST", "/v1/modes/video/start", 400, "validation_error", **kwargs)
        stranger = self.player("cm")
        self.error("POST", "/v1/modes/video/start", stranger, 400, "validation_error", json={"puzzleId": puzzle["id"]})

        session = self.call("POST", "/v1/modes/video/start", who, json={"puzzleId": puzzle["id"]})["sessionId"]
        base = {"sessionId": session, "puzzleId": puzzle["id"], "choice": 2, "answer": ANSWER}
        for weird in ({"choice": 3}, {"choice": -1}, {"choice": 1.0}, {"choice": "1"}, {"choice": True},
                      {"answer": "коротко   "}, {"answer": " " * 50}, {"answer": "а" * 2001}, {"puzzleId": "other"}):
            self.unchanged_after_error(who, "POST", "/v1/attempts/video", 400, "validation_error", json={**base, **weird})
        self.unchanged_after_error(stranger, "POST", "/v1/attempts/video", 400, "validation_error", json=base)

        result = self.call("POST", "/v1/attempts/video", who, json={**base, "choice": 0})
        self.assertEqual((result["correct"], result["review"]["choice"]), (2, "A"))
        self.assertTrue(1 <= result["score"] <= 10)
        self.assertEqual(set(result["review"]), {"choice", "answer", "checklist", "coach", "reply"})
        self.assertEqual(set(result["review"]["checklist"][0]), {"ok", "text"})
        self.assertEqual((result["attempt"]["outcome"], result["attempt"]["axis"], result["attempt"]["mode"]), (None, 4, "video"))

    def test_video_coach_follows_pro(self):
        who = self.player("dm")
        self.pro(who)
        self.call("PATCH", "/v1/me", who, json={"coach": "jurgen"})
        puzzle = self.call("GET", "/v1/puzzles/video", who)
        replies = set()
        for _ in range(2):
            start = self.call("POST", "/v1/modes/video/start", who, json={"puzzleId": puzzle["id"]})
            self.assertIsNone(start["attemptsLeft"])
            result = self.call("POST", "/v1/attempts/video", who, json={"sessionId": start["sessionId"], "puzzleId": puzzle["id"], "choice": 2, "answer": ANSWER})
            self.assertEqual(result["review"]["coach"], "jurgen")
            replies.add(result["review"]["reply"])
        sql("UPDATE users SET pro_until = '2000-01-01' WHERE id = ?", who["user"]["id"])
        expired = self.me(who)
        self.assertEqual((expired["coach"], expired["attemptsLeft"]["video"]), ("base", 0))
        self.error("POST", "/v1/modes/video/start", who, 403, "limit_reached", json={"puzzleId": puzzle["id"]})
        history = self.call("GET", "/v1/me/attempts", who)["items"]
        self.assertEqual([item["review"]["coach"] for item in history], ["jurgen", "jurgen"])

    # --- 9. история ---

    def test_attempt_history_pagination(self):
        who = self.player("ss")
        created = [self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": "ss", "target": None})["attempt"]["id"] for _ in range(7)]
        self.call("POST", "/v1/modes/rush/start", who)
        seen, before = [], None
        while True:
            url = "/v1/me/attempts?limit=2" + (f"&before={before}" if before else "")
            page = self.call("GET", url, who)
            seen += [item["id"] for item in page["items"]]
            before = page["nextBefore"]
            if before is None:
                break
        self.assertEqual(seen, list(reversed(created)))

        newest = self.call("GET", "/v1/me/attempts?limit=1", who)["items"][0]["at"]
        moment = datetime.fromisoformat(newest)
        plus3 = moment.astimezone(timezone(timedelta(hours=3))).isoformat()
        naive = moment.replace(tzinfo=None).isoformat()
        for value in (newest, plus3, naive):
            items = self.call("GET", "/v1/me/attempts", who, params={"before": value})["items"]
            self.assertEqual([item["id"] for item in items], list(reversed(created))[1:], value)
        for bad in ("вчера", "2026-13-01"):
            self.error("GET", "/v1/me/attempts", who, 400, "validation_error", params={"before": bad})
        self.error("GET", "/v1/me/attempts?limit=abc", who, 400, "validation_error")
        self.assertEqual(len(self.call("GET", "/v1/me/attempts?limit=0", who)["items"]), 1)
        self.assertEqual(len(self.call("GET", "/v1/me/attempts?limit=500", who)["items"]), 7)

    # --- 10. рейтинги ---

    def test_leaderboard_window_and_order(self):
        top = [self.player("cm") for _ in range(10)]
        for index, who in enumerate(top):
            sql("UPDATE users SET overall_elo = ? WHERE id = ?", 90000 - index * 10, who["user"]["id"])
        me = top[6]
        board = self.call("GET", "/v1/leaderboards/global?limit=3", me)
        ranks = [item["rank"] for item in board["players"]]
        self.assertEqual(ranks, [1, 2, 3, 5, 6, 7, 8, 9])
        self.assertEqual(board["me"], next(item for item in board["players"] if item["isMe"]))
        self.assertEqual((board["me"]["rank"], board["me"]["elo"]), (7, 89940))
        self.assertEqual([item["id"] for item in board["players"][:3]], [who["user"]["id"] for who in top[:3]])
        self.assertEqual(board["total"], sql("SELECT COUNT(*) AS n FROM users WHERE provider IS NOT NULL")[0]["n"])
        self.assertEqual(set(board["players"][0]), {"id", "rank", "name", "position", "elo", "region", "delta", "isMe"})

        stand = self.client.post("/auth/dev-login", json={"name": "stand-top-" + uuid.uuid4().hex[:6]}).json()["user"]
        sql("UPDATE users SET overall_elo = 999999 WHERE id = ?", stand["id"])
        self.assertNotIn(stand["id"], [item["id"] for item in self.call("GET", "/v1/leaderboards/global", me)["players"]])

        twins = [self.player("cm"), self.player("cm")]
        for who in twins:
            sql("UPDATE users SET overall_elo = 80000 WHERE id = ?", who["user"]["id"])
        ranks = {item["id"]: item["rank"] for item in self.call("GET", "/v1/leaderboards/global?limit=100", me)["players"]}
        self.assertLess(ranks[twins[0]["user"]["id"]], ranks[twins[1]["user"]["id"]])

    def test_leaderboard_delta_and_regions(self):
        who = self.player("st")
        board = self.call("GET", "/v1/leaderboards/global", who)
        self.assertEqual(board["me"]["delta"], 0)
        result = self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": "st", "target": None})
        self.assertEqual(self.call("GET", "/v1/leaderboards/global", who)["me"]["delta"], result["eloDelta"])

        self.error("GET", "/v1/leaderboards/regional", who, 400, "validation_error")
        self.call("PATCH", "/v1/me", who, json={"region": "Армения"})
        mine = self.call("GET", "/v1/leaderboards/regional", who)
        self.assertTrue(all(item["region"] == "Армения" for item in mine["players"]))
        neighbour = self.player("gk")
        self.call("PATCH", "/v1/me", neighbour, json={"region": "Армения"})
        self.assertEqual(self.call("GET", "/v1/leaderboards/regional?region=Армения", who)["total"], mine["total"] + 1)
        foreign = self.call("GET", "/v1/leaderboards/regional?region=Грузия", who)
        self.assertEqual(foreign["me"]["id"], who["user"]["id"])
        self.error("GET", "/v1/leaderboards/regional?region=AM", who, 400, "validation_error")
        self.error("GET", "/v1/leaderboards/weekly", who, 404, "not_found")

    # --- 11. лиги ---

    def test_league_names_and_codes(self):
        owner, other = self.player("cm"), self.player("st")
        for bad in ("", "   ", "a" * 33, "две\nстроки"):
            self.error("POST", "/v1/leagues", owner, 400, "validation_error", json={"name": bad})
        self.error("POST", "/v1/leagues", owner, 400, "validation_error", json={"name": 7})
        first = self.call("POST", "/v1/leagues", owner, json={"name": "  Пятница  "})
        self.assertEqual(first["name"], "Пятница")
        self.assertEqual(set(first), {"id", "name", "code", "membersCount", "myRank", "owner"})
        self.error("POST", "/v1/leagues", owner, 409, "league_name_taken", json={"name": "ПЯТНИЦА"})
        self.call("POST", "/v1/leagues", other, json={"name": "Пятница"})
        self.call("POST", "/v1/leagues", owner, json={"name": "a" * 32})

        codes = {self.call("POST", "/v1/leagues", owner, json={"name": f"Лига {index}"})["code"] for index in range(20)}
        self.assertEqual(len(codes), 20)
        for code in codes:
            self.assertRegex(code, r"^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}$")

        for bad in ("O0O0O0", "I1I1I1", "ABCDE", "ABCDEFG", "", "ABC DE"):
            self.error("POST", "/v1/leagues/join", other, 400, "validation_error", json={"code": bad})
        self.error("POST", "/v1/leagues/join", other, 404, "league_not_found", json={"code": "ZZZZZZ"})
        joined = self.call("POST", "/v1/leagues/join", other, json={"code": f"  {first['code'].lower()} "})
        self.assertEqual(joined["membersCount"], 2)
        self.assertEqual(self.call("POST", "/v1/leagues/join", other, json={"code": first["code"]})["membersCount"], 2)
        self.error("POST", "/v1/leagues", other, 409, "league_name_taken", json={"name": "пятница"})

    def test_league_permissions_and_state(self):
        owner, guest, outsider = self.player("cm"), self.player("st"), self.player("gk")
        league = self.call("POST", "/v1/leagues", owner, json={"name": "Двор"})
        url = f"/v1/leagues/{league['id']}"
        self.call("POST", "/v1/leagues/join", guest, json={"code": league["code"]})

        self.error("GET", url + "/leaderboard", outsider, 404, "league_not_found")
        self.error("PATCH", url, outsider, 404, "league_not_found", json={"name": "x"})
        self.error("DELETE", url, outsider, 404, "league_not_found")
        self.error("PATCH", url, guest, 403, "not_league_owner", json={"name": "Мой двор"})
        self.error("POST", url + "/transfer", guest, 403, "not_league_owner", json={"userId": guest["user"]["id"]})
        self.error("DELETE", url, guest, 403, "not_league_owner")
        self.error("POST", url + "/leave", owner, 403, "not_league_owner")
        self.error("POST", url + "/transfer", owner, 400, "validation_error", json={"userId": outsider["user"]["id"]})
        self.error("GET", "/v1/leagues/NOPE12/leaderboard", owner, 404, "league_not_found")

        table = self.call("GET", url + "/leaderboard", owner)
        self.assertEqual((table["total"], {item["id"] for item in table["players"]}), (2, {owner["user"]["id"], guest["user"]["id"]}))

        before = {item["id"]: item for item in self.call("GET", "/v1/leagues", owner)}[league["id"]]
        self.call("POST", "/v1/attempts/polygon", guest, json={"sceneId": "st", "target": gold("st")})
        self.call("POST", "/v1/attempts/polygon", owner, json={"sceneId": "cm", "target": None})
        after = {item["id"]: item for item in self.call("GET", "/v1/leagues", owner)}[league["id"]]
        self.assertEqual((before["myRank"], after["myRank"]), (1, 2))

        moved = self.call("POST", url + "/transfer", owner, json={"userId": guest["user"]["id"]})
        self.assertEqual(moved["owner"], {"id": guest["user"]["id"], "name": self.me(guest)["name"]})
        self.error("PATCH", url, owner, 403, "not_league_owner", json={"name": "Назад"})
        self.call("POST", url + "/leave", owner, 204)
        self.assertEqual(self.call("GET", "/v1/leagues", guest)[0]["membersCount"], 1)
        self.error("GET", url + "/leaderboard", owner, 404, "league_not_found")
        self.call("POST", "/v1/leagues/join", outsider, json={"code": league["code"]})
        self.call("DELETE", url, guest, 204)
        self.assertEqual(self.call("GET", "/v1/leagues", outsider), [])
        self.error("POST", "/v1/leagues/join", owner, 404, "league_not_found", json={"code": league["code"]})

    # --- 12. что меняет каждая ручка ---

    def test_state_changes_per_endpoint(self):
        who = self.player("dm")
        steps = [
            ("PATCH имя", lambda: self.call("PATCH", "/v1/me", who, json={"name": "Тест"}), {"name"}),
            ("PATCH регион", lambda: self.call("PATCH", "/v1/me", who, json={"region": "Грузия"}), {"region"}),
            ("старт Rush", lambda: self.call("POST", "/v1/modes/rush/start", who), {"attemptsLeft"}),
            ("полигон", lambda: self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": "dm", "target": gold("dm")}),
             {"elo", "positionElo", "eloHistory", "radar", "sessionsCount"}),
            ("лига", lambda: self.call("POST", "/v1/leagues", who, json={"name": "Без следа"}), set()),
            ("рейтинг", lambda: self.call("GET", "/v1/leaderboards/global", who), set()),
            ("история", lambda: self.call("GET", "/v1/me/attempts", who), set()),
            ("видео-пазл", lambda: self.call("GET", "/v1/puzzles/video", who), set()),
            ("sync-subscription", lambda: self.call("POST", "/v1/me/sync-subscription", who), set()),
        ]
        for name, action, expected in steps:
            before = self.me(who)
            action()
            self.assertEqual(self.changed(before, self.me(who)), expected, name)

        before = self.me(who)
        daily = before["daily"]
        result = self.call("POST", "/v1/attempts/polygon", who, json={**daily, "target": gold("dm", daily["mirrored"]), "daily": True})
        # ось сцены dm уже 1.0 после первого золота, второе золото радар не двигает
        self.assertEqual(
            self.changed(before, result["me"]),
            {"elo", "positionElo", "eloHistory", "sessionsCount", "streak", "streakWeek", "dailyDone"},
        )
        self.assertEqual(result["me"]["eloHistory"][:7], before["eloHistory"][:7])

        session = self.call("POST", "/v1/modes/rush/start", who)["sessionId"]
        before = self.me(who)
        result = self.call("POST", "/v1/attempts/rush", who, json={"sessionId": session, "answers": [{"sceneId": "dm", "target": gold("dm")}] * 3})
        self.assertEqual(self.changed(before, result["me"]), {"elo", "positionElo", "eloHistory", "radar", "rushBest", "sessionsCount"})

        puzzle = self.call("GET", "/v1/puzzles/video", who)
        session = self.call("POST", "/v1/modes/video/start", who, json={"puzzleId": puzzle["id"]})["sessionId"]
        before = self.me(who)
        result = self.call("POST", "/v1/attempts/video", who, json={"sessionId": session, "puzzleId": puzzle["id"], "choice": 2, "answer": ANSWER})
        self.assertEqual(self.changed(before, result["me"]), {"elo", "positionElo", "eloHistory", "radar", "sessionsCount"})
        self.assertEqual(result["me"]["sessionsCount"], before["sessionsCount"] + 1)

        before = self.me(who)
        self.call("POST", "/v1/attempts/video", who, json={"sessionId": session, "puzzleId": puzzle["id"], "choice": 0, "answer": "повтор " * 5})
        self.assertEqual(self.me(who), before, "повтор видео поменял Me")


if __name__ == "__main__":
    unittest.main()
