"""Аккаунт для ревьюеров App Store и Google Play (аудит, раздел 3, задача 4, вариант (а)).

Создаёт или заново наполняет аккаунт под тестовую Google-учётку:
- амплуа «опорный» (только у него есть видеоразборы), ELO по итогам ~20 попыток во всех трёх режимах,
  серия задач дня за 5 дней, история ELO за неделю;
- 2 лиги по 5 участников: ревьюер-создатель и 4 служебных игрока (видны только в этих лигах).

Попытки идут через тот же API /v1, что и у приложения: судья, Glicko-2, лимиты и разборы настоящие.
LLM при наполнении выключена, разборы ставит запасная рубрика. Повторный запуск всё пересоздаёт.

Если ревьюер ещё ни разу не входил, создаётся заготовка без sub: при первом входе через Google с этим
подтверждённым email она привязывается к учётке (app/store.py, bind_reviewer).

Запуск на сервере:
    flyctl ssh console -a <приложение> -C "python scripts/seed_reviewer.py --email reviewer@gmail.com"
Флаги: --pro выдаёт PRO на год (для проверки PRO-функций без покупки), --consent сразу ставит согласие на ИИ
(по умолчанию нет: ревьюер должен увидеть экран согласия), --print-token печатает токен доступа на час
(только не на проде), --db путь к базе (по умолчанию FOOTIQ_DB).
"""

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BOTS = [
    ("Артём К.", "cm", 1012), ("Илья С.", "st", 948), ("Тимур Б.", "cb", 887), ("Саня В.", "am", 846),
    ("Мирон Ш.", "lw/rw", 1104), ("Даня Л.", "gk", 921), ("Егор П.", "lm/rm", 869), ("Руслан Х.", "ss", 812),
]
LEAGUES = ("Пятничный футбол", "Школа тактики")
ANSWERS = [
    (2, "Опорный выходит из тени опеки в сторону, чтобы открыть линию паса между линиями, потому что прессингующий перекрывает передачу"),
    (1, "Опускаюсь к защитникам, чтобы помочь в обороне"),
    (2, "Сдвигаюсь вбок из-за спины нападающего, значит центральный защитник может отдать мне вперёд"),
]


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--email", required=True, help="Email тестовой Google-учётки ревьюера")
    parser.add_argument("--name", default="Ревьюер Amplua")
    parser.add_argument("--pro", action="store_true", help="Выдать PRO на год")
    parser.add_argument("--consent", action="store_true", help="Сразу поставить согласие на ИИ-разбор")
    parser.add_argument("--print-token", action="store_true", help="Напечатать токен доступа (не на проде)")
    parser.add_argument("--db", help="Путь к базе SQLite")
    return parser.parse_args()


def main() -> None:
    args = parse()
    if args.db:
        os.environ["FOOTIQ_DB"] = args.db
    os.environ["LLM_PROVIDER"] = ""  # разборы при наполнении ставит запасная рубрика

    import app.store as store
    from fastapi.testclient import TestClient

    import app.main  # noqa: F401  (подключает /v1)
    import app.v1 as v1
    from app.geometry import gold_centroid
    from app.main import _hits, app

    store.init_db()
    user_id = reset_reviewer(store, args.email)
    with store.locked() as connection:
        token, _ = store._issue(connection, user_id)
    headers = {"Authorization": f"Bearer {token}", "X-Timezone-Offset": "180"}
    client = TestClient(app)

    def call(method: str, url: str, **kwargs):
        _hits.clear()
        response = client.request(method, url, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{method} {url}: {response.status_code} {response.text}")
        return response.json() if response.content else None

    # На время наполнения: PRO (снимает дневные лимиты) и согласие на разбор.
    store.set_subscription(user_id, (date.today() + timedelta(days=365)).isoformat())
    store.set_ai_consent(user_id, True)
    call("PATCH", "/v1/me", json={"position": "dm", "region": "Россия", "name": args.name[:20]})

    # Полигон: 10 попыток по разным сценам, большинство в золотую зону.
    scenes = list(v1.SCENES)
    for index in range(10):
        scene = scenes[index % len(scenes)]
        x, y = gold_centroid(v1.SCENES[scene])
        target = None if index in (3, 7) else {"x": x + (6 if index in (5, 9) else 0), "y": y}
        call("POST", "/v1/attempts/polygon", json={"sceneId": scene, "target": target})
    # Задача дня: 5 дней подряд (даты разложим ниже).
    daily = call("GET", "/v1/me")["daily"]
    dailies = [call("POST", "/v1/attempts/polygon", json={**daily, "target": None, "daily": True})["attempt"]["id"] for _ in range(5)]
    # Rush: 3 спринта.
    for sprint in range(3):
        session = call("POST", "/v1/modes/rush/start")["sessionId"]
        answers = []
        for index, scene in enumerate(scenes[: 4 + sprint]):
            x, y = gold_centroid(v1.SCENES[scene])
            answers.append({"sceneId": scene, "target": {"x": x, "y": y} if index != 2 else None})
        call("POST", "/v1/attempts/rush", json={"sessionId": session, "answers": answers})
    # Видеоразборы: 3 ответа разного качества.
    puzzle = call("GET", "/v1/puzzles/video")
    for choice, text in ANSWERS:
        session = call("POST", "/v1/modes/video/start", json={"puzzleId": puzzle["id"]})["sessionId"]
        call("POST", "/v1/attempts/video", json={"sessionId": session, "puzzleId": puzzle["id"], "choice": choice, "answer": text})

    spread_history(store, user_id, dailies)

    # Лиги: ревьюер создатель, 4 служебных игрока в каждой.
    bots = ensure_bots(store)
    for number, name in enumerate(LEAGUES):
        league = call("POST", "/v1/leagues", json={"name": name})
        for bot in bots[number * 4 : number * 4 + 4]:
            store.join_league(bot, league["code"])

    # Итоговое состояние: PRO только по флагу, согласие по умолчанию снимаем.
    store.set_subscription(user_id, (date.today() + timedelta(days=365)).isoformat() if args.pro else None)
    store.set_ai_consent(user_id, args.consent)

    me = call("GET", "/v1/me")
    summary = {
        "userId": user_id,
        "email": args.email,
        "boundToGoogle": bool(store.user_row(user_id)["sub"]),
        "elo": me["elo"],
        "sessionsCount": me["sessionsCount"],
        "streak": me["streak"],
        "isPro": me["isPro"],
        "aiConsentAt": me["aiConsentAt"],
        "leagues": [{"code": item["code"], "name": item["name"], "members": item["membersCount"]} for item in call("GET", "/v1/leagues")],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.print_token:
        if os.environ.get("AMPLUA_ENV") == "prod":
            print("--print-token на проде не работает", file=sys.stderr)
        else:
            print(f"accessToken (1 час): {token}")


def reset_reviewer(store, email: str) -> str:
    """Находит аккаунт ревьюера (или Google-аккаунт с этим email) и очищает его прогресс; иначе создаёт заготовку."""
    with store.locked() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE provider = 'google' AND lower(email) = lower(?) ORDER BY review DESC LIMIT 1", (email,)
        ).fetchone()
        if row is None:
            user_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO users (id, name, provider, sub, email, timezone, country, review)
                VALUES (?, ?, 'google', NULL, ?, '180', 'RU', 1)
                """,
                (user_id, f"google:{user_id}", email),
            )
            return user_id
        user_id = row["id"]
        for code in [item["code"] for item in connection.execute("SELECT code FROM leagues WHERE owner_id = ?", (user_id,))]:
            connection.execute("DELETE FROM league_members WHERE code = ?", (code,))
            connection.execute("DELETE FROM leagues WHERE code = ?", (code,))
        for table in ("league_members", "attempts", "llm_log"):
            connection.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        connection.execute(
            """
            UPDATE users SET review = 1, overall_elo = 800, position_elo = '{}', glicko_rd = 350, glicko_sigma = 0.06,
                position_glicko = '{}', streak_count = 0, last_daily_on = NULL, position_changed_on = NULL,
                primary_position = NULL, timezone = '180', banned_at = NULL, ban_reason = NULL
            WHERE id = ?
            """,
            (user_id,),
        )
        return user_id


def spread_history(store, user_id: str, dailies: list[str]) -> None:
    """Раскладывает попытки по последним 9 дням: появляется история ELO, серия задач дня 5 дней подряд."""
    now = datetime.now(timezone.utc)
    with store.locked() as connection:
        rows = connection.execute(
            "SELECT id FROM attempts WHERE user_id = ? AND id NOT IN ({}) ORDER BY rowid".format(",".join("?" * len(dailies))),
            (user_id, *dailies),
        ).fetchall()
        for index, row in enumerate(rows):
            moment = now - timedelta(days=8 - index * 8 / max(1, len(rows) - 1), minutes=5)
            connection.execute("UPDATE attempts SET created_at = ? WHERE id = ?", (moment.strftime(store.STAMP), row["id"]))
        for offset, attempt_id in enumerate(reversed(dailies)):
            moment = now - timedelta(days=offset, minutes=1)
            connection.execute("UPDATE attempts SET created_at = ? WHERE id = ?", (moment.strftime(store.STAMP), attempt_id))
        today = (now + timedelta(minutes=180)).date()
        connection.execute("UPDATE users SET streak_count = ?, last_daily_on = ? WHERE id = ?", (len(dailies), today.isoformat(), user_id))


def ensure_bots(store) -> list[str]:
    ids = []
    with store.locked() as connection:
        for number, (name, position, elo) in enumerate(BOTS, start=1):
            sub = f"review-bot-{number}"
            row = connection.execute("SELECT id FROM users WHERE provider = 'google' AND sub = ?", (sub,)).fetchone()
            if row is None:
                bot_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO users (id, name, provider, sub, display_name, primary_position, overall_elo, country, review_bot)
                    VALUES (?, ?, 'google', ?, ?, ?, ?, 'RU', 1)
                    """,
                    (bot_id, f"bot:{sub}", sub, name, position, elo),
                )
                row = {"id": bot_id}
            ids.append(row["id"])
    return ids


if __name__ == "__main__":
    main()
