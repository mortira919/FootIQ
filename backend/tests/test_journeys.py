import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="footiq-qa-")) / "qa.sqlite"

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.geometry import gold_centroid
from app.main import ValidateIn, VideoAnswerIn, _hits, app, validate_pass, video_answer
from app.puzzles import load_puzzles
from app.store import apply_glicko, connect, init_db

PUZZLES = load_puzzles()
DM = PUZZLES["dm-shadow-1"]
ANSWER = "опорник между линий прикрывает тень и линию паса потому что надо"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def video_rows(user_id: str) -> int:
    with connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM attempts WHERE user_id = ? AND mode = 'video'",
            (user_id,),
        ).fetchone()
    return row["n"]


def elo_of(user_id: str) -> float:
    with connect() as connection:
        return connection.execute("SELECT overall_elo FROM users WHERE id = ?", (user_id,)).fetchone()["overall_elo"]


class Journeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        _hits.clear()
        self.name = "qa-" + uuid.uuid4().hex[:10]

    def login(self, name: str | None = None) -> tuple[str, dict]:
        response = self.client.post("/auth/dev-login", json={"name": name or self.name})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        return body["access_token"], body["user"]

    def as_dm(self, token: str) -> dict:
        response = self.client.patch(
            "/users/me/position",
            headers=auth(token),
            json={"primary_position": "dm"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def me(self, token: str) -> dict:
        response = self.client.get("/users/me", headers=auth(token))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_happy_path_keeps_streak_and_hides_video_key(self):
        token, user = self.login()
        self.assertEqual(user["overall_elo"], 800)
        self.assertEqual(user["rank"], "Новичок")
        self.as_dm(token)
        x, y = gold_centroid(DM)
        played = self.client.post(
            "/attempts/polygon/validate",
            headers=auth(token),
            json={"puzzle_id": DM["id"], "mirrored": False, "target": {"x": x, "y": y}, "mode": "polygon"},
        )
        self.assertEqual(played.status_code, 200, played.text)
        self.assertEqual(played.json()["outcome"], "gold")
        self.assertEqual(played.json()["reason"], "optimal")
        self.assertGreater(played.json()["overall_elo"], 800)

        first = self._close_daily(token)
        second = self._close_daily(token)
        self.assertEqual(first.json()["streak_count"], 1)
        self.assertEqual(second.json()["streak_count"], 1)
        self.assertEqual(self.me(token)["streak_count"], 1)
        self.assertGreater(len(self.client.get("/users/me/attempts", headers=auth(token)).json()["attempts"]), 2)

        opened = self.client.get("/puzzles/video/next", headers=auth(token))
        self.assertEqual(opened.status_code, 200, opened.text)
        for secret in ("correct", "factors", "ground_truth", "role_keywords"):
            self.assertNotIn(secret, opened.json())
        answered = self.client.post(
            "/attempts/video/answer",
            headers=auth(token),
            json={"puzzle_id": opened.json()["id"], "option": "c", "text": ANSWER, "persona": "Пеп"},
        )
        self.assertEqual(answered.status_code, 200, answered.text)
        self.assertEqual(answered.json()["persona"], "Ассистент")
        self.assertGreaterEqual(answered.json()["score"], 7)
        again = self.client.post(
            "/attempts/video/answer",
            headers=auth(token),
            json={"puzzle_id": opened.json()["id"], "option": "C", "text": ANSWER},
        )
        self.assertEqual(again.status_code, 403)

        bare = self.client.get("/users/me")
        self.assertEqual(bare.status_code, 401)
        self.assertEqual(self.client.get("/users/me", headers=auth("not-a-token")).status_code, 401)

    def test_two_sessions_share_state_and_attempts_stay_private(self):
        token_a, _ = self.login()
        self.as_dm(token_a)
        token_b, _ = self.login(self.name)
        self.assertNotEqual(token_a, token_b)
        self.assertEqual(self.client.get("/users/me", headers=auth(token_a)).status_code, 401)
        self.assertEqual(self.me(token_b)["primary_position"], "dm")
        x, y = gold_centroid(DM)
        played = self.client.post(
            "/attempts/polygon/validate",
            headers=auth(token_b),
            json={"puzzle_id": DM["id"], "mirrored": False, "target": {"x": x, "y": y}},
        )
        attempt_id = played.json()["attempt_id"]
        other_name = self.name + "-b"
        token_other, _ = self.login(other_name)
        self.as_dm(token_other)
        foreign = self.client.get("/users/me/attempts", headers=auth(token_other)).json()["attempts"]
        self.assertNotIn(attempt_id, [item["id"] for item in foreign])
        self.assertEqual(self.me(token_b)["name"], self.name)
        self.assertEqual(self.me(token_other)["name"], other_name)

    def test_video_open_then_position_change_does_not_trap_the_user(self):
        from app.main import VIDEOS

        probe = dict(next(iter(VIDEOS.values())))
        probe["id"] = "vid-st-probe"
        probe["target_positions"] = ["st"]
        VIDEOS[probe["id"]] = probe
        try:
            token, _ = self.login()
            self.as_dm(token)
            opened = self.client.get("/puzzles/video/next", headers=auth(token))
            self.assertEqual(opened.status_code, 200, opened.text)
            self.assertEqual(self.client.post("/users/me/tier", headers=auth(token), json={"tier": "pro"}).status_code, 200)
            moved = self.client.patch("/users/me/position", headers=auth(token), json={"primary_position": "st"})
            self.assertEqual(moved.status_code, 200, moved.text)
            nxt = self.client.get("/puzzles/video/next", headers=auth(token))
            if nxt.status_code == 200:
                self.assertIn("st", nxt.json()["target_positions"])
            else:
                self.assertEqual(nxt.status_code, 404)
        finally:
            VIDEOS.pop("vid-st-probe", None)
        blocked = self.client.post(
            "/attempts/video/answer",
            headers=auth(token),
            json={"puzzle_id": opened.json()["id"], "option": "C", "text": ANSWER},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(video_rows(self.me(token)["id"]), 0)

    def test_parallel_daily_counts_both_ratings_and_one_streak(self):
        token, _ = self.login()
        self.as_dm(token)
        user = self.me(token)
        daily = self.client.get("/puzzles/daily", headers=auth(token)).json()
        puzzle = PUZZLES[daily["id"]]
        x, y = gold_centroid(puzzle)
        if daily["mirrored"]:
            x = 68 - x
        body = ValidateIn(
            puzzle_id=daily["id"],
            mirrored=daily["mirrored"],
            target={"x": x, "y": y},
            mode="daily",
        )
        seq_token, _ = self.login(self.name + "-seq")
        self.as_dm(seq_token)
        seq = self.me(seq_token)
        validate_pass(body, seq)
        validate_pass(body, seq)
        expected = elo_of(seq["id"])

        def hit():
            try:
                validate_pass(body, user)
                return 200
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _: hit(), range(2)))
        self.assertEqual(codes.count(200), 2)
        self.assertEqual(self.me(token)["streak_count"], 1)
        self.assertAlmostEqual(elo_of(user["id"]), expected, delta=0.05)

    def test_parallel_video_answer_is_single_winner(self):
        token, _ = self.login()
        self.as_dm(token)
        opened = self.client.get("/puzzles/video/next", headers=auth(token))
        self.assertEqual(opened.status_code, 200, opened.text)
        user = self.me(token)
        body = VideoAnswerIn(puzzle_id=opened.json()["id"], option="C", text=ANSWER, persona="Ассистент")

        def hit():
            try:
                video_answer(body, user)
                return 200
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(lambda _: hit(), range(8)))
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(video_rows(user["id"]), 1)

    def test_parallel_glicko_does_not_drop_updates(self):
        token, _ = self.login()
        self.as_dm(token)
        user = self.me(token)
        seq_token, _ = self.login(self.name + "-seq")
        self.as_dm(seq_token)
        seq = self.me(seq_token)
        for _ in range(6):
            apply_glicko(seq["id"], "dm", 2, 1.0)
        expected = elo_of(seq["id"])
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: apply_glicko(user["id"], "dm", 2, 1.0), range(6)))
        self.assertAlmostEqual(elo_of(user["id"]), expected, delta=0.05)

    def test_dirty_login_is_literal_and_rate_limit_has_no_retry_after(self):
        dirty = "o'brian; DROP TABLE users;-- " + uuid.uuid4().hex[:6]
        first, user = self.login(dirty)
        second, again = self.login(dirty)
        self.assertEqual(user["id"], again["id"])
        self.assertEqual(self.client.get("/users/me", headers=auth(first)).status_code, 401)
        self.assertEqual(self.me(second)["name"], dirty)
        self.assertEqual(self.client.get("/health").status_code, 200)
        _hits.clear()
        last = None
        for index in range(21):
            last = self.client.post("/auth/dev-login", json={"name": f"burst-{index}-{uuid.uuid4().hex[:4]}"})
        self.assertEqual(last.status_code, 429)
        self.assertNotIn("retry-after", {key.lower() for key in last.headers})

    def test_unknown_mode_does_not_skip_the_daily_check(self):
        token, _ = self.login()
        self.as_dm(token)
        x, y = gold_centroid(DM)
        rejected = self.client.post(
            "/attempts/polygon/validate",
            headers=auth(token),
            json={"puzzle_id": DM["id"], "mirrored": False, "target": {"x": x, "y": y}, "mode": "nope"},
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(self.me(token)["overall_elo"], 800)

    def test_pro_expires_and_can_review_twice_while_active(self):
        token, user = self.login()
        self.as_dm(token)
        upgraded = self.client.post("/users/me/tier", headers=auth(token), json={"tier": "pro"})
        self.assertEqual(upgraded.status_code, 200, upgraded.text)
        self.assertEqual(upgraded.json()["subscription_tier"], "pro")
        self.assertIsNotNone(upgraded.json()["pro_until"])
        opened = self.client.get("/puzzles/video/next", headers=auth(token))
        payload = {"puzzle_id": opened.json()["id"], "option": "C", "text": ANSWER, "persona": "Пеп"}
        first = self.client.post("/attempts/video/answer", headers=auth(token), json=payload)
        second = self.client.post("/attempts/video/answer", headers=auth(token), json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["persona"], "Пеп")
        moved = self.client.patch("/users/me/position", headers=auth(token), json={"primary_position": "cm"})
        self.assertEqual(moved.status_code, 200, moved.text)
        with connect() as connection:
            connection.execute("UPDATE users SET pro_until = '2000-01-01' WHERE id = ?", (user["id"],))
        self.assertEqual(self.me(token)["subscription_tier"], "free")
        blocked = self.client.patch("/users/me/position", headers=auth(token), json={"primary_position": "cb"})
        self.assertEqual(blocked.status_code, 403, blocked.text)

    def test_rush_preview_does_not_spend_the_daily_limit(self):
        token, _ = self.login()
        self.as_dm(token)
        for _ in range(3):
            preview = self.client.get("/puzzles/rush/batch", headers=auth(token))
            self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(self._finish_rush(token).status_code, 200)
        self.assertEqual(self._finish_rush(token).status_code, 200)
        self.assertEqual(self._finish_rush(token).status_code, 403)

    def test_grade_cache_belongs_to_one_user(self):
        token_a, _ = self.login()
        self.as_dm(token_a)
        opened = self.client.get("/puzzles/video/next", headers=auth(token_a))
        payload = {"puzzle_id": opened.json()["id"], "option": "C", "text": ANSWER, "persona": "Ассистент"}
        mine = self.client.post("/attempts/video/answer", headers=auth(token_a), json=payload)
        self.assertEqual(mine.status_code, 200, mine.text)
        token_b, _ = self.login(self.name + "-b")
        self.as_dm(token_b)
        self.client.get("/puzzles/video/next", headers=auth(token_b))
        theirs = self.client.post("/attempts/video/answer", headers=auth(token_b), json=payload)
        self.assertEqual(theirs.status_code, 200, theirs.text)
        self.assertIs(theirs.json()["cached"], False)

    def _finish_rush(self, token: str):
        batch = self.client.get("/puzzles/rush/batch", headers=auth(token))
        if batch.status_code != 200:
            return batch
        first = batch.json()["puzzles"][0]
        puzzle = PUZZLES[first["id"]]
        x, y = gold_centroid(puzzle)
        if first["mirrored"]:
            x = 68 - x
        return self.client.post(
            "/attempts/rush",
            headers=auth(token),
            json={"answers": [{"puzzle_id": first["id"], "mirrored": first["mirrored"], "target": {"x": x, "y": y}}]},
        )

    def _close_daily(self, token: str):
        daily = self.client.get("/puzzles/daily", headers=auth(token))
        self.assertEqual(daily.status_code, 200, daily.text)
        body = daily.json()
        puzzle = PUZZLES[body["id"]]
        x, y = gold_centroid(puzzle)
        if body["mirrored"]:
            x = 68 - x
        return self.client.post(
            "/attempts/polygon/validate",
            headers=auth(token),
            json={"puzzle_id": body["id"], "mirrored": body["mirrored"], "target": {"x": x, "y": y}, "mode": "daily"},
        )


if __name__ == "__main__":
    unittest.main()
