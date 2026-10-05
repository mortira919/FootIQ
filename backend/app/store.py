from app.glicko import START_RD, START_SIGMA, puzzle_rating, update_rating
from app.position_rule import can_change_position
from app.rank import rank_for
from app.streak import advance_streak, visible_streak
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("FOOTIQ_DB", ROOT / "data" / "footiq.sqlite"))

POSITIONS = ("gk", "cb", "rb/lb", "dm", "cm", "am", "lm/rm", "lw/rw", "st", "ss")
DEFAULT_TZ = "Asia/Almaty"
PRO_DAYS = 30


class QuotaExceeded(Exception):
    pass


def _zone(name: str | None):
    try:
        return timezone(timedelta(minutes=int(name)))
    except (TypeError, ValueError):
        pass
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def local_today(row: sqlite3.Row | None = None) -> date:
    name = DEFAULT_TZ
    if row is not None and "timezone" in row.keys() and row["timezone"]:
        name = row["timezone"]
    return datetime.now(_zone(name)).date()


def day_bounds(row: sqlite3.Row | None) -> tuple[str, str]:
    zone = _zone(row["timezone"] if row is not None and "timezone" in row.keys() and row["timezone"] else DEFAULT_TZ)
    start = datetime.combine(local_today(row), time.min, tzinfo=zone).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    pattern = "%Y-%m-%d %H:%M:%S"
    return start.strftime(pattern), end.strftime(pattern)


def effective_tier(row: sqlite3.Row | None) -> str:
    raw = "free"
    if row is not None and "subscription_tier" in row.keys() and row["subscription_tier"]:
        raw = row["subscription_tier"]
    if raw != "pro":
        return "free"
    until = row["pro_until"] if row is not None and "pro_until" in row.keys() else None
    if not until or date.fromisoformat(until) < local_today(row):
        return "free"
    return "pro"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _add_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    names = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    if column not in names:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                primary_position TEXT,
                overall_elo REAL NOT NULL DEFAULT 800,
                position_elo TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                puzzle_id TEXT NOT NULL,
                action TEXT NOT NULL,
                x REAL,
                y REAL,
                outcome TEXT NOT NULL,
                reason TEXT NOT NULL,
                mirrored INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'polygon',
                elo_delta INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _add_column(connection, "users", "overall_elo", "REAL NOT NULL DEFAULT 800")
        _add_column(connection, "users", "position_elo", "TEXT NOT NULL DEFAULT '{}'")
        _add_column(connection, "attempts", "mirrored", "INTEGER NOT NULL DEFAULT 0")
        _add_column(connection, "attempts", "mode", "TEXT NOT NULL DEFAULT 'polygon'")
        _add_column(connection, "attempts", "elo_delta", "INTEGER NOT NULL DEFAULT 0")
        _add_column(connection, "attempts", "user_text", "TEXT")
        _add_column(connection, "attempts", "verdict", "TEXT")
        _add_column(connection, "users", "subscription_tier", "TEXT NOT NULL DEFAULT 'free'")
        _add_column(connection, "users", "streak_count", "INTEGER NOT NULL DEFAULT 0")
        _add_column(connection, "users", "last_daily_on", "TEXT")
        _add_column(connection, "users", "position_changed_on", "TEXT")
        _add_column(connection, "users", "glicko_rd", "REAL NOT NULL DEFAULT 350")
        _add_column(connection, "users", "glicko_sigma", "REAL NOT NULL DEFAULT 0.06")
        _add_column(connection, "users", "position_glicko", "TEXT NOT NULL DEFAULT '{}'")
        _add_column(connection, "users", "country", "TEXT")
        _add_column(connection, "users", "timezone", "TEXT NOT NULL DEFAULT 'Asia/Almaty'")
        _add_column(connection, "users", "pro_until", "TEXT")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS leagues (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS league_members (
                code TEXT NOT NULL,
                user_id TEXT NOT NULL,
                PRIMARY KEY (code, user_id)
            );
            """
        )
        for column in ("provider", "sub", "email", "display_name", "coach", "apple_refresh"):
            _add_column(connection, "users", column, "TEXT")
        _add_column(connection, "attempts", "position", "TEXT")
        _add_column(connection, "sessions", "kind", "TEXT NOT NULL DEFAULT 'dev'")
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS users_identity ON users(provider, sub);
            -- клиент разбирает region как обязательную строку, по умолчанию первый регион списка, как в LocalBackend
            UPDATE users SET country = 'RU' WHERE provider IS NOT NULL AND country IS NULL;
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cache_columns = [item[1] for item in connection.execute("PRAGMA table_info(semantic_cache)")]
        if cache_columns and "user_id" not in cache_columns:
            connection.execute("DROP TABLE semantic_cache")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_cache (
                puzzle_id TEXT NOT NULL,
                position TEXT NOT NULL,
                persona TEXT NOT NULL,
                text_key TEXT NOT NULL,
                user_id TEXT NOT NULL,
                response TEXT NOT NULL,
                PRIMARY KEY (puzzle_id, position, persona, text_key, user_id)
            )
            """
        )


def login_dev(name: str) -> tuple[str, sqlite3.Row]:
    cleaned = name.strip()
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE name = ?", (cleaned,)).fetchone()
        if row is not None and row["provider"]:
            raise ValueError("Это имя занято игроком приложения")
        if row is None:
            user_id = str(uuid.uuid4())
            connection.execute("INSERT INTO users (id, name) VALUES (?, ?)", (user_id, cleaned))
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        token = uuid.uuid4().hex
        connection.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, row["id"]))
    return token, row


def user_from_token(token: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.kind = 'dev'
            """,
            (token,),
        ).fetchone()


def set_position(user_id: str, position: str) -> tuple[sqlite3.Row, str | None]:
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        changed_on = row["position_changed_on"] if "position_changed_on" in row.keys() else None
        today = local_today(row)
        allowed, opens = can_change_position(
            row["primary_position"], position, changed_on, today, effective_tier(row)
        )
        if not allowed:
            return row, opens
        stamp = changed_on
        if row["primary_position"] not in (None, position):
            stamp = today.isoformat()
        connection.execute(
            "UPDATE users SET primary_position = ?, position_changed_on = ? WHERE id = ?",
            (position, stamp, user_id),
        )
        updated = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return updated, None


def list_attempts(user_id: str, limit: int = 30) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, puzzle_id, mode, outcome, reason, elo_delta, created_at
            FROM attempts
            WHERE user_id = ? AND outcome != 'start'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "puzzle_id": row["puzzle_id"],
            "mode": row["mode"],
            "outcome": row["outcome"],
            "reason": row["reason"],
            "elo_delta": row["elo_delta"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def save_attempt(user_id, puzzle_id, x, y, outcome, reason, mirrored, mode, elo_delta) -> str:
    attempt_id = str(uuid.uuid4())
    with connect() as connection:
        _insert_attempt(connection, attempt_id, user_id, puzzle_id, x, y, outcome, reason, mirrored, mode, elo_delta)
    return attempt_id


@contextmanager
def locked():
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")
    finally:
        connection.close()


STAMP = "%Y-%m-%d %H:%M:%S.%f"


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime(STAMP)


def _insert_attempt(
    connection, attempt_id, user_id, puzzle_id, x, y, outcome, reason, mirrored, mode, elo_delta, position=None
) -> None:
    connection.execute(
        """
        INSERT INTO attempts (
            id, user_id, puzzle_id, action, x, y, outcome, reason, mirrored, mode, elo_delta, position, created_at
        )
        VALUES (?, ?, ?, 'target', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (attempt_id, user_id, puzzle_id, x, y, outcome, reason, int(bool(mirrored)), mode, elo_delta, position, now_stamp()),
    )


def _glicko(connection, user_id: str, position: str, difficulty: int, score: float) -> tuple[sqlite3.Row, int]:
    row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    rating = row["overall_elo"] if row["overall_elo"] is not None else 800
    rd = row["glicko_rd"] if "glicko_rd" in row.keys() and row["glicko_rd"] is not None else START_RD
    sigma = row["glicko_sigma"] if "glicko_sigma" in row.keys() and row["glicko_sigma"] is not None else START_SIGMA
    new_r, new_rd, new_sigma, delta = update_rating(rating, rd, sigma, puzzle_rating(difficulty), score)
    by_position = json.loads(row["position_glicko"] or "{}") if "position_glicko" in row.keys() else {}
    state = by_position.get(position) or {"r": 800, "rd": START_RD, "sigma": START_SIGMA}
    pos_r, pos_rd, pos_sigma, _ = update_rating(state["r"], state["rd"], state["sigma"], puzzle_rating(difficulty), score)
    by_position[position] = {"r": pos_r, "rd": pos_rd, "sigma": pos_sigma}
    shown = json.loads(row["position_elo"] or "{}")
    shown[position] = round(pos_r)
    connection.execute(
        """
        UPDATE users
        SET overall_elo = ?, glicko_rd = ?, glicko_sigma = ?, position_glicko = ?, position_elo = ?
        WHERE id = ?
        """,
        (new_r, new_rd, new_sigma, json.dumps(by_position), json.dumps(shown), user_id),
    )
    updated = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return updated, delta


def _mark_daily(connection, row: sqlite3.Row) -> sqlite3.Row:
    today = local_today(row)
    count, last_day = advance_streak(row["streak_count"] or 0, row["last_daily_on"], today)
    connection.execute(
        "UPDATE users SET streak_count = ?, last_daily_on = ? WHERE id = ?",
        (count, last_day, row["id"]),
    )
    return connection.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()


def _count_mode(connection, user_id: str, mode: str, row: sqlite3.Row) -> int:
    start, end = day_bounds(row)
    found = connection.execute(
        """
        SELECT COUNT(*) AS n FROM attempts
        WHERE user_id = ? AND mode = ? AND created_at >= ? AND created_at < ?
        """,
        (user_id, mode, start, end),
    ).fetchone()
    return found["n"]


def apply_glicko(user_id: str, position: str, difficulty: int, score: float) -> tuple[sqlite3.Row, int]:
    with locked() as connection:
        return _glicko(connection, user_id, position, difficulty, score)


def commit_polygon(
    user_id, position, difficulty, score, puzzle_id, x, y, outcome, reason, mirrored, mode
) -> tuple[sqlite3.Row, int, str]:
    attempt_id = str(uuid.uuid4())
    with locked() as connection:
        updated, delta = _glicko(connection, user_id, position, difficulty, score)
        if mode == "daily":
            updated = _mark_daily(connection, updated)
        _insert_attempt(connection, attempt_id, user_id, puzzle_id, x, y, outcome, reason, mirrored, mode, delta, position)
    return updated, delta, attempt_id


def commit_rush(user_id, position, difficulty, score, outcome) -> tuple[sqlite3.Row, int, str]:
    attempt_id = str(uuid.uuid4())
    with locked() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if _count_mode(connection, user_id, "rush-result", row) >= 2:
            raise QuotaExceeded("Лимит Free: 2 спринта в день")
        updated, delta = _glicko(connection, user_id, position, difficulty, score)
        _insert_attempt(
            connection, attempt_id, user_id, "rush", None, None, outcome, "rush", False, "rush-result", delta, position
        )
    return updated, delta, attempt_id


def commit_video(user_id, position, difficulty, score, puzzle_id, option, text, verdict) -> tuple[sqlite3.Row, int, str]:
    attempt_id = str(uuid.uuid4())
    with locked() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if effective_tier(row) != "pro" and _count_mode(connection, user_id, "video", row) >= 1:
            raise QuotaExceeded("Лимит Free: 1 видеоразбор в день")
        updated, delta = _glicko(connection, user_id, position, difficulty, score)
        verdict["elo_delta"] = delta
        connection.execute(
            """
            INSERT INTO attempts (
                id, user_id, puzzle_id, action, outcome, reason, mode, elo_delta, user_text, verdict, position, created_at
            )
            VALUES (?, ?, ?, 'answer', 'video', ?, 'video', ?, ?, ?, ?, ?)
            """,
            (
                attempt_id, user_id, puzzle_id, option, delta, text,
                json.dumps(verdict, ensure_ascii=False), position, now_stamp(),
            ),
        )
    return updated, delta, attempt_id


def rush_starts_today(user_id: str) -> int:
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _count_mode(connection, user_id, "rush-result", row)


def video_rows_today(user_id: str, mode: str) -> list[sqlite3.Row]:
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        start, end = day_bounds(row)
        return connection.execute(
            """
            SELECT * FROM attempts
            WHERE user_id = ? AND mode = ? AND created_at >= ? AND created_at < ?
            ORDER BY created_at
            """,
            (user_id, mode, start, end),
        ).fetchall()


def attempts_for_radar(user_id: str) -> list[sqlite3.Row]:
    with connect() as connection:
        return connection.execute(
            """
            SELECT puzzle_id, outcome, mode, verdict, position
            FROM attempts
            WHERE user_id = ? AND outcome != 'start'
            """,
            (user_id,),
        ).fetchall()


def set_country(user_id: str, country: str) -> sqlite3.Row:
    with connect() as connection:
        connection.execute("UPDATE users SET country = ? WHERE id = ?", (country, user_id))
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def set_tier(user_id: str, tier: str) -> sqlite3.Row:
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        until = (local_today(row) + timedelta(days=PRO_DAYS)).isoformat() if tier == "pro" else None
        connection.execute(
            "UPDATE users SET subscription_tier = ?, pro_until = ? WHERE id = ?",
            (tier, until, user_id),
        )
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def ranking(country: str | None = None, user_ids: list[str] | None = None) -> list[dict]:
    query = "SELECT name, primary_position, overall_elo, country FROM users WHERE overall_elo IS NOT NULL"
    params: list = []
    if country is not None:
        query += " AND country = ?"
        params.append(country)
    if user_ids is not None:
        if not user_ids:
            return []
        marks = ",".join("?" for _ in user_ids)
        query += f" AND id IN ({marks})"
        params.extend(user_ids)
    query += " ORDER BY overall_elo DESC LIMIT 50"
    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "name": row["name"],
            "primary_position": row["primary_position"],
            "overall_elo": row["overall_elo"],
            "country": row["country"],
        }
        for row in rows
    ]


def create_league(owner_id: str, name: str) -> str:
    code = uuid.uuid4().hex[:6].upper()
    with connect() as connection:
        connection.execute("INSERT INTO leagues (code, name, owner_id) VALUES (?, ?, ?)", (code, name, owner_id))
        connection.execute("INSERT INTO league_members (code, user_id) VALUES (?, ?)", (code, owner_id))
    return code


def join_league(user_id: str, code: str) -> bool:
    with connect() as connection:
        league = connection.execute("SELECT code FROM leagues WHERE code = ?", (code,)).fetchone()
        if league is None:
            return False
        connection.execute("INSERT OR IGNORE INTO league_members (code, user_id) VALUES (?, ?)", (code, user_id))
    return True


def league_member_ids(code: str) -> list[str] | None:
    with connect() as connection:
        league = connection.execute("SELECT code FROM leagues WHERE code = ?", (code,)).fetchone()
        if league is None:
            return None
        rows = connection.execute("SELECT user_id FROM league_members WHERE code = ?", (code,)).fetchall()
    return [row["user_id"] for row in rows]


def cached_grade(puzzle_id: str, position: str, persona: str, text_key: str, user_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT response FROM semantic_cache
            WHERE puzzle_id = ? AND position = ? AND persona = ? AND text_key = ? AND user_id = ?
            """,
            (puzzle_id, position, persona, text_key, user_id),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["response"])


def store_grade(puzzle_id: str, position: str, persona: str, text_key: str, user_id: str, response: dict) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO semantic_cache (puzzle_id, position, persona, text_key, user_id, response)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (puzzle_id, position, persona, text_key, user_id, json.dumps(response, ensure_ascii=False)),
        )


def public_user(row: sqlite3.Row) -> dict:
    today = local_today(row)
    last_day = row["last_daily_on"] if "last_daily_on" in row.keys() else None
    count = row["streak_count"] if "streak_count" in row.keys() else 0
    elo = row["overall_elo"] if row["overall_elo"] is not None else 800
    return {
        "id": row["id"],
        "name": row["name"],
        "primary_position": row["primary_position"],
        "overall_elo": elo,
        "rank": rank_for(elo),
        "position_elo": json.loads(row["position_elo"] or "{}"),
        "subscription_tier": effective_tier(row),
        "pro_until": row["pro_until"] if "pro_until" in row.keys() else None,
        "timezone": row["timezone"] if "timezone" in row.keys() and row["timezone"] else DEFAULT_TZ,
        "streak_count": visible_streak(count or 0, last_day, today),
        "position_changed_on": row["position_changed_on"] if "position_changed_on" in row.keys() else None,
        "country": row["country"] if "country" in row.keys() else None,
    }



ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400


def _user(connection, user_id: str) -> sqlite3.Row:
    return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def user_row(user_id: str) -> sqlite3.Row:
    with connect() as connection:
        return _user(connection, user_id)


def _issue(connection, user_id: str) -> tuple[str, str]:
    connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    connection.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (user_id,))
    access, refresh = uuid.uuid4().hex, uuid.uuid4().hex
    connection.execute("INSERT INTO sessions (token, user_id, kind) VALUES (?, ?, 'v1')", (access, user_id))
    connection.execute("INSERT INTO refresh_tokens (token, user_id) VALUES (?, ?)", (refresh, user_id))
    return access, refresh


def login_provider(provider: str, sub: str, email: str | None, name: str | None) -> tuple[str, str, sqlite3.Row]:
    with locked() as connection:
        row = connection.execute("SELECT * FROM users WHERE provider = ? AND sub = ?", (provider, sub)).fetchone()
        if row is None:
            user_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO users (id, name, provider, sub, email, display_name, timezone, country)
                VALUES (?, ?, ?, ?, ?, ?, '0', 'RU')
                """,
                (user_id, f"{provider}:{user_id}", provider, sub, email, name),
            )
        else:
            user_id = row["id"]
            connection.execute(
                "UPDATE users SET email = COALESCE(?, email), display_name = COALESCE(display_name, ?) WHERE id = ?",
                (email, name, user_id),
            )
        access, refresh = _issue(connection, user_id)
        return access, refresh, _user(connection, user_id)


def refresh_session(token: str) -> tuple[str, str] | None:
    with locked() as connection:
        found = connection.execute(
            "SELECT user_id FROM refresh_tokens WHERE token = ? AND created_at > datetime('now', ?)",
            (token, f"-{REFRESH_TTL} seconds"),
        ).fetchone()
        if found is None:
            return None
        return _issue(connection, found["user_id"])


def logout(token: str) -> None:
    with locked() as connection:
        found = connection.execute("SELECT user_id FROM refresh_tokens WHERE token = ?", (token,)).fetchone()
        if found is not None:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (found["user_id"],))
            connection.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (found["user_id"],))


def user_from_fresh_token(token: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.kind = 'v1' AND sessions.created_at > datetime('now', ?)
            """,
            (token, f"-{ACCESS_TTL} seconds"),
        ).fetchone()


def update_user(user_id: str, **fields) -> sqlite3.Row:
    assert set(fields) <= {"display_name", "country", "coach", "timezone", "apple_refresh"}, fields
    with connect() as connection:
        for column, value in fields.items():
            connection.execute(f"UPDATE users SET {column} = ? WHERE id = ?", (value, user_id))
        return _user(connection, user_id)


def delete_user(user_id: str) -> None:
    with locked() as connection:
        owned = [row["code"] for row in connection.execute("SELECT code FROM leagues WHERE owner_id = ?", (user_id,))]
        for code in owned:
            connection.execute("DELETE FROM league_members WHERE code = ?", (code,))
            connection.execute("DELETE FROM leagues WHERE code = ?", (code,))
        for table in ("league_members", "attempts", "sessions", "refresh_tokens", "semantic_cache"):
            connection.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))


def count_today(row: sqlite3.Row, mode: str) -> int:
    with connect() as connection:
        return _count_mode(connection, row["id"], mode, row)


def attempts_since(user_id: str, start: str) -> list[sqlite3.Row]:
    with connect() as connection:
        return connection.execute(
            """
            SELECT mode, elo_delta, created_at FROM attempts
            WHERE user_id = ? AND outcome != 'start' AND created_at >= ?
            """,
            (user_id, start),
        ).fetchall()


def player_stats(user_id: str) -> sqlite3.Row:
    with connect() as connection:
        return connection.execute(
            """
            SELECT
                COUNT(*) AS sessions,
                MAX(CASE WHEN mode = 'rush-result' THEN json_extract(verdict, '$.solved') END) AS rush_best
            FROM attempts
            WHERE user_id = ? AND outcome != 'start'
            """,
            (user_id,),
        ).fetchone()


def attempts_page(user_id: str, limit: int, before: str | None) -> list[sqlite3.Row]:
    with connect() as connection:
        return connection.execute(
            """
            SELECT * FROM attempts
            WHERE user_id = ? AND outcome != 'start' AND created_at < COALESCE(?, '9999')
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (user_id, before, limit),
        ).fetchall()


def start_session(user_id: str, mode: str, puzzle_id: str, position: str, daily_limit: int | None) -> tuple[str, int]:
    session_id = str(uuid.uuid4())
    with locked() as connection:
        row = _user(connection, user_id)
        used = _count_mode(connection, user_id, mode, row)
        if daily_limit is not None and used >= daily_limit:
            raise QuotaExceeded(mode)
        # Сессия режима это строка попытки: старт уже тратит лимит, ответ дописывает исход.
        connection.execute(
            """
            INSERT INTO attempts (id, user_id, puzzle_id, action, outcome, reason, mode, position, created_at)
            VALUES (?, ?, ?, 'target', 'start', 'start', ?, ?, ?)
            """,
            (session_id, user_id, puzzle_id, mode, position, now_stamp()),
        )
    return session_id, used + 1


def session_row(user_id: str, session_id: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM attempts WHERE id = ? AND user_id = ?", (session_id, user_id)
        ).fetchone()


def finish_session(session_id: str, difficulty: int, score: float, outcome: str, reason: str, text, verdict: dict) -> sqlite3.Row:
    with locked() as connection:
        session = connection.execute("SELECT * FROM attempts WHERE id = ?", (session_id,)).fetchone()
        if session["outcome"] == "start":
            _, delta = _glicko(connection, session["user_id"], session["position"], difficulty, score)
            connection.execute(
                "UPDATE attempts SET outcome = ?, reason = ?, elo_delta = ?, user_text = ?, verdict = ? WHERE id = ?",
                (outcome, reason, delta, text, json.dumps(verdict, ensure_ascii=False), session_id),
            )
        return connection.execute("SELECT * FROM attempts WHERE id = ?", (session_id,)).fetchone()


def board_rows(user_ids: list[str] | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT users.*, (
            SELECT elo_delta FROM attempts
            WHERE attempts.user_id = users.id AND outcome != 'start'
            ORDER BY created_at DESC, rowid DESC LIMIT 1
        ) AS last_delta
        FROM users
        WHERE provider IS NOT NULL
    """
    params: list = []
    if user_ids is not None:
        query += f" AND id IN ({','.join('?' for _ in user_ids) or 'NULL'})"
        params = list(user_ids)
    # ponytail: вся таблица в память; на десятках тысяч игроков нужен индекс по ELO и окно вокруг игрока
    query += " ORDER BY overall_elo DESC, created_at, rowid"
    with connect() as connection:
        return connection.execute(query, params).fetchall()


def leagues_of(user_id: str) -> list[sqlite3.Row]:
    with connect() as connection:
        return connection.execute(
            """
            SELECT leagues.* FROM leagues
            JOIN league_members ON league_members.code = leagues.code
            WHERE league_members.user_id = ?
            ORDER BY leagues.name
            """,
            (user_id,),
        ).fetchall()


def league_row(code: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute("SELECT * FROM leagues WHERE code = ?", (code,)).fetchone()


def insert_league(code: str, name: str, owner_id: str) -> bool:
    with connect() as connection:
        try:
            connection.execute("INSERT INTO leagues (code, name, owner_id) VALUES (?, ?, ?)", (code, name, owner_id))
        except sqlite3.IntegrityError:
            return False
        connection.execute("INSERT INTO league_members (code, user_id) VALUES (?, ?)", (code, owner_id))
    return True


def update_league(code: str, **fields) -> None:
    assert set(fields) <= {"name", "owner_id"}, fields
    with connect() as connection:
        for column, value in fields.items():
            connection.execute(f"UPDATE leagues SET {column} = ? WHERE code = ?", (value, code))


def leave_league(code: str, user_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM league_members WHERE code = ? AND user_id = ?", (code, user_id))


def delete_league(code: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM league_members WHERE code = ?", (code,))
        connection.execute("DELETE FROM leagues WHERE code = ?", (code,))
