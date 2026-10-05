import tempfile
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="footiq-v1-")) / "v1.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401  (точка входа: main подключает v1)
import app.v1 as v1
from app.geometry import gold_centroid
from app.main import _hits, app
from app.store import connect, init_db



class V1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.real_verify = v1.verify_identity
        v1.verify_identity = lambda provider, token: {"sub": token, "email": f"{token}@example.com"}
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        v1.verify_identity = cls.real_verify

    def setUp(self):
        _hits.clear()

    def login(self, sub: str | None = None) -> dict:
        response = self.client.post("/v1/auth/google", json={"idToken": sub or uuid.uuid4().hex})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        body["headers"] = {"Authorization": f"Bearer {body['accessToken']}", "X-Timezone-Offset": "180"}
        return body

    def call(self, method: str, url: str, who: dict, status: int = 200, **kwargs):
        response = self.client.request(method, url, headers=who["headers"], **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        return response.json() if response.content else None

    def error(self, method: str, url: str, who: dict, status: int, **kwargs) -> dict:
        return self.call(method, url, who, status, **kwargs)["error"]

    def player(self, position: str = "fb") -> dict:
        who = self.login()
        self.call("PATCH", "/v1/me", who, json={"position": position})
        return who

    def test_login_refresh_logout_delete(self):
        sub = uuid.uuid4().hex
        first = self.login(sub)
        me = first["user"]
        self.assertEqual((me["elo"], me["position"], me["provider"]), (800, None, "google"))
        self.assertEqual(me["email"], f"{sub}@example.com")
        self.assertRegex(me["name"], r"^Игрок \d{4}$")
        self.assertEqual(me["attemptsLeft"], {"polygon": None, "rush": 2, "video": 1})
        self.assertEqual(me["eloHistory"], [800] * 8)
        self.assertEqual(me["radar"], [None] * 5)
        self.assertEqual(me["streakWeek"], [False] * 7)
        self.assertIsNone(me["daily"])
        self.assertEqual(me["coach"], "base")

        second = self.login(sub)
        self.assertEqual(second["user"]["id"], me["id"])
        self.assertEqual(self.error("GET", "/v1/me", first, 401)["code"], "unauthorized")

        pair = self.client.post("/v1/auth/refresh", json={"refreshToken": second["refreshToken"]}).json()
        self.assertEqual(set(pair), {"accessToken", "refreshToken"})
        reused = self.client.post("/v1/auth/refresh", json={"refreshToken": second["refreshToken"]})
        self.assertEqual(reused.status_code, 401)
        fresh = {"headers": {"Authorization": f"Bearer {pair['accessToken']}"}}
        self.call("GET", "/v1/me", fresh)

        self.assertEqual(self.client.post("/v1/auth/logout", json={"refreshToken": pair["refreshToken"]}).status_code, 204)
        self.assertEqual(self.error("GET", "/v1/me", fresh, 401)["code"], "unauthorized")

        doomed = self.player()
        league = self.call("POST", "/v1/leagues", doomed, json={"name": "Удаляемая"})
        guest = self.login()
        self.call("POST", "/v1/leagues/join", guest, json={"code": league["code"]})
        self.call("DELETE", "/v1/me", doomed, 204)
        self.assertEqual(self.call("GET", "/v1/leagues", guest), [])

    def test_errors_use_envelope(self):
        who = self.login()
        bad = self.client.post("/v1/auth/google", json={})
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (400, "validation_error"))
        self.assertEqual(self.error("GET", "/v1/me", {"headers": {}}, 401)["code"], "unauthorized")
        offset = {"headers": {**who["headers"], "X-Timezone-Offset": "abc"}}
        self.assertEqual(self.error("GET", "/v1/me", offset, 400)["code"], "validation_error")
        self.assertIn("detail", self.client.get("/users/me").json())

    def test_profile_rules(self):
        who = self.login()
        self.assertEqual(self.error("PATCH", "/v1/me", who, 400, json={"name": " x "})["code"], "validation_error")
        self.assertEqual(self.error("PATCH", "/v1/me", who, 400, json={"position": "rb/lb"})["code"], "validation_error")
        self.assertEqual(self.error("PATCH", "/v1/me", who, 400, json={"region": "KZ"})["code"], "validation_error")
        self.assertEqual(self.error("PATCH", "/v1/me", who, 403, json={"coach": "pep"})["code"], "pro_required")

        me = self.call("PATCH", "/v1/me", who, json={"name": "  Артём ", "position": "fb", "region": "Казахстан"})
        self.assertEqual((me["name"], me["position"], me["region"]), ("Артём", "fb", "Казахстан"))
        self.assertIsNone(me["positionLockDays"])
        self.assertEqual(me["daily"]["sceneId"], "fb")
        with connect() as connection:
            stored = connection.execute("SELECT primary_position, timezone FROM users WHERE id = ?", (me["id"],)).fetchone()
        self.assertEqual((stored["primary_position"], stored["timezone"]), ("rb/lb", "180"))

        self.call("PATCH", "/v1/me", who, json={"position": "winger"})
        locked = self.error("PATCH", "/v1/me", who, 403, json={"position": "cm"})
        self.assertEqual((locked["code"], locked["daysLeft"]), ("position_locked", 30))
        self.assertEqual(self.call("GET", "/v1/me", who)["positionLockDays"], 30)

        with connect() as connection:
            connection.execute(
                "UPDATE users SET subscription_tier = 'pro', pro_until = ? WHERE id = ?",
                ((date.today() + timedelta(days=5)).isoformat(), me["id"]),
            )
        me = self.call("PATCH", "/v1/me", who, json={"coach": "pep", "position": "cm"})
        self.assertEqual((me["coach"], me["position"], me["isPro"]), ("pep", "cm", True))
        self.assertEqual(me["attemptsLeft"], {"polygon": None, "rush": None, "video": None})
        with connect() as connection:
            connection.execute("UPDATE users SET pro_until = '2000-01-01' WHERE id = ?", (me["id"],))
        self.assertEqual(self.call("GET", "/v1/me", who)["coach"], "base")

    def test_polygon_and_daily(self):
        who = self.player("fb")
        scene = v1.SCENES["fb"]
        x, y = gold_centroid(scene)
        self.assertEqual(self.error("POST", "/v1/attempts/polygon", who, 400, json={"sceneId": "zz"})["code"], "validation_error")

        result = self.call("POST", "/v1/attempts/polygon", who, json={"sceneId": "fb", "target": {"x": x, "y": y}})
        self.assertEqual(result["reason"], "optimal")
        self.assertGreater(result["eloDelta"], 0)
        attempt = result["attempt"]
        self.assertEqual((attempt["mode"], attempt["position"], attempt["outcome"], attempt["daily"]), ("polygon", "fb", "gold", False))
        me = result["me"]
        self.assertEqual(me["elo"], 800 + result["eloDelta"])
        self.assertEqual((me["eloHistory"][0], me["eloHistory"][-1]), (800, me["elo"]))
        self.assertEqual(me["positionElo"]["fb"], me["elo"])
        self.assertEqual(me["radar"][scene["axis"]], 1.0)

        daily = me["daily"]
        wrong = {"sceneId": "fb", "mirrored": not daily["mirrored"], "target": None, "daily": True}
        self.assertEqual(self.error("POST", "/v1/attempts/polygon", who, 400, json=wrong)["code"], "validation_error")
        done = self.call("POST", "/v1/attempts/polygon", who, json={**daily, "target": None, "daily": True})
        self.assertEqual(done["reason"], "timeout")
        self.assertEqual((done["me"]["streak"], done["me"]["dailyDone"]), (1, True))
        self.assertEqual(done["me"]["streakWeek"], [False] * 6 + [True])
        self.assertEqual(done["me"]["sessionsCount"], 2)

        page = self.call("GET", "/v1/me/attempts?limit=1", who)
        self.assertTrue(page["items"][0]["daily"])
        self.assertIsNotNone(page["nextBefore"])

    def test_rush_session(self):
        who = self.player("fb")
        start = self.call("POST", "/v1/modes/rush/start", who)
        self.assertEqual(start["attemptsLeft"], 1)
        self.assertEqual(self.call("GET", "/v1/me", who)["attemptsLeft"]["rush"], 1)

        x, y = gold_centroid(v1.SCENES["fb"])
        answers = [{"sceneId": "fb", "target": {"x": x, "y": y}}] + [{"sceneId": "cm", "target": None}] * 4
        body = {"sessionId": start["sessionId"], "answers": answers}
        result = self.call("POST", "/v1/attempts/rush", who, json=body)
        self.assertEqual(result["attempt"]["title"], "Серия 1 из 4")
        self.assertEqual((result["attempt"]["mode"], result["attempt"]["axis"]), ("rush", 3))
        self.assertEqual(result["me"]["rushBest"], 1)
        again = self.call("POST", "/v1/attempts/rush", who, json={**body, "answers": answers[:1]})
        self.assertEqual((again["eloDelta"], again["attempt"]), (result["eloDelta"], result["attempt"]))
        self.assertEqual(again["me"]["elo"], result["me"]["elo"])

        self.call("POST", "/v1/modes/rush/start", who)
        self.assertEqual(self.error("POST", "/v1/modes/rush/start", who, 403)["code"], "limit_reached")

        stranger = self.player("cm")
        self.assertEqual(self.error("POST", "/v1/attempts/rush", stranger, 400, json=body)["code"], "validation_error")

        late = self.call("POST", "/v1/modes/rush/start", stranger)
        with connect() as connection:
            connection.execute(
                "UPDATE attempts SET created_at = datetime('now', '-10 minutes') WHERE id = ?", (late["sessionId"],)
            )
        expired = self.error("POST", "/v1/attempts/rush", stranger, 409, json={**body, "sessionId": late["sessionId"]})
        self.assertEqual(expired["code"], "session_expired")

    def test_video_session(self):
        who = self.player("dm")
        puzzle = self.call("GET", "/v1/puzzles/video", who)
        self.assertEqual((puzzle["position"], puzzle["sceneId"]), ("dm", "dm"))
        self.assertNotIn("correct", puzzle)
        missing = self.error("POST", "/v1/modes/video/start", who, 400, json={"puzzleId": "nope"})
        self.assertEqual(missing["code"], "validation_error")

        start = self.call("POST", "/v1/modes/video/start", who, json={"puzzleId": puzzle["id"]})
        self.assertEqual(start["attemptsLeft"], 0)
        over = self.error("POST", "/v1/modes/video/start", who, 403, json={"puzzleId": puzzle["id"]})
        self.assertEqual(over["code"], "limit_reached")

        body = {
            "sessionId": start["sessionId"],
            "puzzleId": puzzle["id"],
            "choice": 2,
            "answer": "опорник прикрывает зону и выходит из тени, чтобы открыть линию паса",
        }
        result = self.call("POST", "/v1/attempts/video", who, json=body)
        self.assertEqual(result["correct"], 2)
        self.assertEqual((result["review"]["choice"], result["review"]["coach"]), ("C", "base"))
        self.assertGreaterEqual(result["score"], 8)
        self.assertEqual(result["attempt"]["review"], result["review"])
        self.assertEqual(result["me"]["radar"][4], result["score"] / 10)

        again = self.call("POST", "/v1/attempts/video", who, json={**body, "choice": 0, "answer": "другой ответ целиком"})
        self.assertEqual((again["score"], again["eloDelta"], again["review"]), (result["score"], result["eloDelta"], result["review"]))
        self.assertEqual(self.call("GET", "/v1/me", who)["sessionsCount"], 1)

    def test_leaderboards_and_leagues(self):
        owner, guest = self.player("cm"), self.player("st")
        self.call("PATCH", "/v1/me", owner, json={"region": "Россия"})

        world = self.call("GET", "/v1/leaderboards/global", owner)
        self.assertTrue(world["me"]["isMe"])
        self.assertIn(world["me"], world["players"])
        regional = self.call("GET", "/v1/leaderboards/regional?region=Казахстан", owner)
        self.assertEqual(regional["me"]["id"], owner["user"]["id"])
        self.assertEqual(self.error("GET", "/v1/leaderboards/regional?region=KZ", owner, 400)["code"], "validation_error")

        league = self.call("POST", "/v1/leagues", owner, json={"name": "Пятничный футбол"})
        self.assertRegex(league["code"], r"^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}$")
        self.assertEqual((league["membersCount"], league["myRank"], league["owner"]["id"]), (1, 1, owner["user"]["id"]))
        taken = self.error("POST", "/v1/leagues", owner, 409, json={"name": "ПЯТНИЧНЫЙ футбол"})
        self.assertEqual(taken["code"], "league_name_taken")

        self.assertEqual(self.error("POST", "/v1/leagues/join", guest, 400, json={"code": "O0"})["code"], "validation_error")
        self.assertEqual(self.error("POST", "/v1/leagues/join", guest, 404, json={"code": "ZZZZZZ"})["code"], "league_not_found")
        joined = self.call("POST", "/v1/leagues/join", guest, json={"code": league["code"].lower()})
        self.assertEqual(joined["membersCount"], 2)
        self.call("POST", "/v1/leagues/join", guest, json={"code": league["code"]})

        table = self.call("GET", f"/v1/leagues/{league['id']}/leaderboard", guest)
        self.assertEqual(table["total"], 2)
        rename = self.error("PATCH", f"/v1/leagues/{league['id']}", guest, 403, json={"name": "Моя"})
        self.assertEqual(rename["code"], "not_league_owner")
        self.assertEqual(self.error("POST", f"/v1/leagues/{league['id']}/leave", owner, 403)["code"], "not_league_owner")

        renamed = self.call("PATCH", f"/v1/leagues/{league['id']}", owner, json={"name": "Субботний"})
        self.assertEqual(renamed["name"], "Субботний")
        moved = self.call("POST", f"/v1/leagues/{league['id']}/transfer", owner, json={"userId": guest["user"]["id"]})
        self.assertEqual(moved["owner"]["id"], guest["user"]["id"])
        self.call("POST", f"/v1/leagues/{league['id']}/leave", owner, 204)
        self.assertEqual(self.call("GET", "/v1/leagues", owner), [])
        self.call("DELETE", f"/v1/leagues/{league['id']}", guest, 204)
        self.assertEqual(self.error("POST", "/v1/leagues/join", owner, 404, json={"code": league["code"]})["code"], "league_not_found")


if __name__ == "__main__":
    unittest.main()
