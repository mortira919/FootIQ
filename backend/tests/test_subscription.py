"""Этап 4: вебхук RevenueCat и проверка статуса подписки (аудит, раздел 3, задача 5)."""

import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import app.store as store

store.DB_PATH = Path(tempfile.mkdtemp(prefix="amplua-sub-")) / "sub.sqlite"

from fastapi.testclient import TestClient

import app.main  # noqa: F401
import app.v1 as v1
from app.main import _hits, app
from app.store import connect, init_db
from tests.mock_http import MockServer

SECRET = "rc-webhook-secret"
DAY_MS = 86_400_000


def fake_identity(provider: str, token: str) -> dict:
    return {"sub": token, "email": f"{token}@example.com"}


def iso(ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


class Subscription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.mock = MockServer()
        cls.saved_env = {name: os.environ.get(name) for name in ("REVENUECAT_WEBHOOK_SECRET", "REVENUECAT_SECRET_KEY", "REVENUECAT_API_URL")}
        os.environ["REVENUECAT_WEBHOOK_SECRET"] = SECRET
        os.environ.pop("REVENUECAT_SECRET_KEY", None)
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

    def player(self) -> dict:
        who = self.client.post("/v1/auth/google", json={"idToken": uuid.uuid4().hex}).json()
        who["headers"] = {"Authorization": f"Bearer {who['accessToken']}", "X-Timezone-Offset": "180"}
        return who

    def me(self, who: dict) -> dict:
        return self.client.get("/v1/me", headers=who["headers"]).json()

    def send(self, who: dict | None, kind: str, event_id: str | None = None, secret: str | None = f"Bearer {SECRET}", **fields):
        now = int(time.time() * 1000)
        event = {
            "id": event_id or uuid.uuid4().hex,
            "type": kind,
            "app_user_id": who["user"]["id"] if who else None,
            "original_app_user_id": who["user"]["id"] if who else None,
            "aliases": [who["user"]["id"]] if who else [],
            "entitlement_ids": ["pro"],
            "event_timestamp_ms": now,
            "expiration_at_ms": now + 30 * DAY_MS,
            "environment": "SANDBOX",
            "period_type": "NORMAL",
            **fields,
        }
        headers = {"Authorization": secret} if secret else {}
        return self.client.post("/v1/webhooks/revenuecat", json={"api_version": "1.0", "event": event}, headers=headers)

    def pro(self, who: dict) -> bool:
        return self.me(who)["isPro"]

    # --- критерии этапа 4 ---

    def test_wrong_secret_is_401(self):
        who = self.player()
        for secret in ("Bearer wrong", "wrong", None):
            response = self.send(who, "INITIAL_PURCHASE", secret=secret)
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (401, "unauthorized"))
        self.assertFalse(self.pro(who))
        # Секрет в дашборде можно задать без «Bearer»: принимаем и так.
        self.assertEqual(self.send(who, "INITIAL_PURCHASE", secret=SECRET).status_code, 200)
        self.assertTrue(self.pro(who))

    def test_duplicate_event_changes_nothing_second_time(self):
        who = self.player()
        first = self.send(who, "INITIAL_PURCHASE", event_id="evt-dup-1")
        self.assertEqual(first.json(), {"ok": True, "duplicate": False})
        self.assertTrue(self.pro(who))
        self.assertEqual(self.send(who, "EXPIRATION", event_id="evt-dup-2").status_code, 200)
        self.assertFalse(self.pro(who))
        again = self.send(who, "INITIAL_PURCHASE", event_id="evt-dup-1")
        self.assertEqual((again.status_code, again.json()["duplicate"]), (200, True))
        self.assertFalse(self.pro(who))
        with connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM rc_events WHERE id = 'evt-dup-1'").fetchone()[0], 1)

    def test_expiration_and_refund_remove_pro_and_coach(self):
        for kind, extra in (("EXPIRATION", {}), ("CANCELLATION", {"cancel_reason": "CUSTOMER_SUPPORT"})):
            who = self.player()
            self.send(who, "INITIAL_PURCHASE")
            me = self.client.patch("/v1/me", headers=who["headers"], json={"coach": "jurgen"}).json()
            self.assertEqual((me["isPro"], me["coach"]), (True, "jurgen"))
            self.send(who, kind, **extra)
            me = self.me(who)
            self.assertEqual((me["isPro"], me["coach"], me["attemptsLeft"]["rush"]), (False, "base", 2), kind)

    # --- каждое событие выставляет isPro правильно ---

    def test_event_table(self):
        now = int(time.time() * 1000)
        future, past = now + 10 * DAY_MS, now - 2 * DAY_MS
        who = self.player()
        steps = [
            ("TEST", {}, False),
            ("INITIAL_PURCHASE", {}, True),
            ("RENEWAL", {"expiration_at_ms": future}, True),
            ("CANCELLATION", {"cancel_reason": "UNSUBSCRIBE", "expiration_at_ms": future}, True),
            ("UNCANCELLATION", {"expiration_at_ms": future}, True),
            ("BILLING_ISSUE", {"grace_period_expiration_at_ms": future}, True),
            ("BILLING_ISSUE", {"grace_period_expiration_at_ms": None}, True),
            ("PRODUCT_CHANGE", {"expiration_at_ms": future}, True),
            ("SUBSCRIPTION_PAUSED", {}, True),
            ("CANCELLATION", {"cancel_reason": "CUSTOMER_SUPPORT"}, False),
            ("REFUND_REVERSED", {"expiration_at_ms": future}, True),
            ("EXPIRATION", {"expiration_at_ms": past}, False),
            ("RENEWAL", {"expiration_at_ms": future}, True),
            ("CANCELLATION", {"cancel_reason": "BILLING_ERROR", "expiration_at_ms": past}, False),
            ("NON_RENEWING_PURCHASE", {"expiration_at_ms": None}, True),
            ("INVOICE_ISSUANCE", {}, True),
        ]
        for kind, extra, expected in steps:
            self.assertEqual(self.send(who, kind, **extra).status_code, 200, kind)
            self.assertEqual(self.pro(who), expected, f"{kind} {extra}")

    def test_alias_and_unknown_user(self):
        who = self.player()
        response = self.send(None, "INITIAL_PURCHASE", app_user_id="$RCAnonymousID:abc", original_app_user_id="$RCAnonymousID:abc", aliases=["$RCAnonymousID:abc", who["user"]["id"]])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.pro(who))
        stranger = self.send(None, "INITIAL_PURCHASE", app_user_id="nobody", original_app_user_id="nobody", aliases=[])
        self.assertEqual(stranger.status_code, 200)

    def test_transfer_moves_pro(self):
        old, new = self.player(), self.player()
        self.send(old, "INITIAL_PURCHASE")
        self.send(None, "TRANSFER", transferred_from=[old["user"]["id"]], transferred_to=[new["user"]["id"]])
        self.assertEqual((self.pro(old), self.pro(new)), (False, True))

    # --- sync-subscription спрашивает REST API ---

    def test_sync_subscription_uses_rest_api(self):
        who = self.player()
        uid = who["user"]["id"]
        now = int(time.time() * 1000)
        state = {"expires": iso(now + 5 * DAY_MS), "grace": None}
        self.mock.routes[("GET", f"/v1/subscribers/{uid}")] = lambda request: (
            200,
            {"subscriber": {"entitlements": {"pro": {"expires_date": state["expires"], "grace_period_expires_date": state["grace"], "product_identifier": "amplua_pro_month"}}}},
        )
        os.environ.update({"REVENUECAT_SECRET_KEY": "sk_test", "REVENUECAT_API_URL": self.mock.url + "/v1"})
        try:
            me = self.client.post("/v1/me/sync-subscription", headers=who["headers"]).json()
            self.assertTrue(me["isPro"])
            request = self.mock.calls("GET", f"/v1/subscribers/{uid}")[-1]
            self.assertEqual(request["headers"]["Authorization"], "Bearer sk_test")

            state["expires"] = iso(now - DAY_MS)
            self.assertFalse(self.client.post("/v1/me/sync-subscription", headers=who["headers"]).json()["isPro"])
            state["grace"] = iso(now + 3 * DAY_MS)
            self.assertTrue(self.client.post("/v1/me/sync-subscription", headers=who["headers"]).json()["isPro"])

            # После вебхука сервер сверяется с REST: истина у RevenueCat, даже если событие пришло старое.
            state["expires"], state["grace"] = iso(now - DAY_MS), None
            self.send(who, "RENEWAL")
            self.assertFalse(self.pro(who))

            # RevenueCat недоступен: статус не меняется.
            state["expires"] = iso(now + 5 * DAY_MS)
            self.client.post("/v1/me/sync-subscription", headers=who["headers"])
            self.mock.routes[("GET", f"/v1/subscribers/{uid}")] = (503, {"message": "down"})
            self.assertTrue(self.client.post("/v1/me/sync-subscription", headers=who["headers"]).json()["isPro"])
        finally:
            os.environ.pop("REVENUECAT_SECRET_KEY", None)
            os.environ.pop("REVENUECAT_API_URL", None)

    def test_sync_without_key_keeps_status(self):
        who = self.player()
        self.assertFalse(self.client.post("/v1/me/sync-subscription", headers=who["headers"]).json()["isPro"])


if __name__ == "__main__":
    unittest.main()
