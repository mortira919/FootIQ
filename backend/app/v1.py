"""Слой /v1 под контракт Flutter-клиента (API.md). Игровая логика общая со стендом."""

import json
import logging
import os
import re
import secrets
import time as clock
from datetime import date, datetime, time, timedelta, timezone

import httpx
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.responses import JSONResponse, PlainTextResponse
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.elo import score_for
from app.geometry import judge
from app.main import PUZZLES, VIDEOS, _daily_for, _hit, limit_ip
from app.radar import POINTS
from app.store import (
    POSITIONS,
    STAMP,
    QuotaExceeded,
    _zone,
    attempts_for_radar,
    attempts_page,
    attempts_since,
    board_rows,
    commit_polygon,
    count_today,
    delete_league,
    delete_user,
    effective_tier,
    finish_session,
    insert_league,
    join_league,
    league_member_ids,
    league_row,
    leagues_of,
    leave_league,
    local_today,
    login_provider,
    logout,
    player_stats,
    refresh_session,
    session_row,
    set_position,
    start_session,
    update_league,
    update_user,
    user_from_fresh_token,
    user_row,
)
from app.streak import visible_streak
from app.video import grade

log = logging.getLogger("footiq.v1")
router = APIRouter(prefix="/v1")

# У клиента крайние роли называются короче, остальные коды совпадают.
CLIENT_TO_OURS = {"fb": "rb/lb", "wm": "lm/rm", "winger": "lw/rw"}
OURS_TO_CLIENT = {ours: client for client, ours in CLIENT_TO_OURS.items()}
REGIONS = {"Россия": "RU", "Казахстан": "KZ", "Беларусь": "BY", "Узбекистан": "UZ", "Армения": "AM", "Грузия": "GE"}
REGION_NAMES = {code: name for name, code in REGIONS.items()}
COACHES = {"base": "Ассистент", "pep": "Пеп", "jose": "Жозе", "jurgen": "Юрген"}
FREE_LIMITS = {"rush": 2, "video": 1}
MODE_ROWS = {"rush": "rush-result", "video": "video"}
RUSH_LIVES = 3
RUSH_WINDOW = 210
LEAGUE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LEAGUE_CODE = re.compile(f"[{LEAGUE_ALPHABET}]{{6}}")
STATUS_CODES = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    429: "rate_limited",
}


class Body(BaseModel):
    # strict: "true" не станет bool, "1" не станет числом, 1.5 не станет int
    model_config = ConfigDict(strict=True)


Short = Annotated[str, Field(max_length=64)]
Long = Annotated[str, Field(max_length=4096)]
Coord = Annotated[float, Field(allow_inf_nan=False)]


def to_client(position: str | None) -> str | None:
    return OURS_TO_CLIENT.get(position, position) if position else None


CLIENT_ROLES = {to_client(position): position for position in POSITIONS}
# Сцена клиента называется кодом роли, у нас по одной сцене на роль.
SCENES = {to_client(puzzle["target_positions"][0]): puzzle for puzzle in PUZZLES.values()}


# --- ошибки ---


def fail(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def invalid(message: str) -> HTTPException:
    return fail(400, "validation_error", message)


async def http_error(request: Request, exc):
    if not request.url.path.startswith("/v1"):
        return await http_exception_handler(request, exc)
    detail = exc.detail
    if not (isinstance(detail, dict) and "code" in detail):
        detail = {"code": STATUS_CODES.get(exc.status_code, "error"), "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


async def validation_error(request: Request, exc):
    if not request.url.path.startswith("/v1"):
        return await request_validation_exception_handler(request, exc)
    first = (exc.errors() or [{}])[0]
    field = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "validation_error", "message": f"Неверное поле {field}".strip()}},
    )


async def server_error(request: Request, exc: Exception):
    if not request.url.path.startswith("/v1"):
        return PlainTextResponse("Internal Server Error", status_code=500)
    log.exception("Ошибка на %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": {"code": "internal", "message": "Ошибка на сервере, попробуй ещё раз"}})


# --- вход через Google и Apple ---

PROVIDERS = {
    "google": ("GOOGLE_CLIENT_ID", "https://www.googleapis.com/oauth2/v3/certs", ["accounts.google.com", "https://accounts.google.com"]),
    "apple": ("APPLE_BUNDLE_ID", "https://appleid.apple.com/auth/keys", ["https://appleid.apple.com"]),
}
_jwks: dict[str, jwt.PyJWKClient] = {}


def verify_identity(provider: str, token: str) -> dict:
    env, url, issuers = PROVIDERS[provider]
    audience = os.environ.get(env)
    if not audience:
        raise fail(503, "auth_not_configured", "Вход пока не настроен на сервере")
    try:
        client = _jwks.setdefault(url, jwt.PyJWKClient(url))
        key = client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=["RS256"], audience=audience.split(","), issuer=issuers,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
    except jwt.PyJWKClientConnectionError as exc:
        raise fail(503, "auth_unavailable", "Сервер входа не отвечает, попробуй позже") from exc
    except jwt.PyJWTError as exc:
        raise fail(401, "unauthorized", "Не удалось подтвердить вход") from exc


def _apple_secret() -> str | None:
    team, key_id, key = (os.environ.get(name) for name in ("APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY"))
    if not (team and key_id and key):
        return None
    now = int(clock.time())
    claims = {"iss": team, "iat": now, "exp": now + 300, "aud": "https://appleid.apple.com", "sub": os.environ["APPLE_BUNDLE_ID"]}
    return jwt.encode(claims, key.replace("\\n", "\n"), algorithm="ES256", headers={"kid": key_id})


def _apple_call(path: str, data: dict) -> dict | None:
    secret = _apple_secret()
    if secret is None:
        log.warning("Apple %s пропущен: нет APPLE_TEAM_ID / APPLE_KEY_ID / APPLE_PRIVATE_KEY", path)
        return None
    payload = {"client_id": os.environ["APPLE_BUNDLE_ID"], "client_secret": secret, **data}
    try:
        response = httpx.post(f"https://appleid.apple.com/auth/{path}", data=payload, timeout=10)
        response.raise_for_status()
        return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        log.exception("Apple %s не прошёл", path)
        return None


# --- игрок и Me ---


def _with_offset(row, header: str | None):
    if header is None:
        return row
    try:
        offset = int(header)
    except ValueError:
        offset = None
    if offset is None or not -720 <= offset <= 840:
        raise invalid("X-Timezone-Offset: минуты от UTC, от -720 до 840")
    if str(offset) != row["timezone"]:
        row = update_user(row["id"], timezone=str(offset))
    return row


def player(
    authorization: str | None = Header(default=None),
    x_timezone_offset: str | None = Header(default=None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise fail(401, "unauthorized", "Нужно войти заново")
    row = user_from_fresh_token(authorization.removeprefix("Bearer ").strip())
    if row is None:
        raise fail(401, "unauthorized", "Сессия истекла")
    _hit("user:" + row["id"], 60)
    return _with_offset(row, x_timezone_offset)


def _position(row) -> str:
    if not row["primary_position"]:
        raise invalid("Сначала выбери амплуа")
    return row["primary_position"]


def _iso(stamp: str) -> str:
    return stamp.replace(" ", "T") + "Z"


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)


def display_name(row) -> str:
    return row["display_name"] or f"Игрок {int(row['id'].replace('-', '')[:8], 16) % 9000 + 1000}"


def coach_of(row) -> str:
    return row["coach"] if effective_tier(row) == "pro" and row["coach"] in COACHES else "base"


def lock_days(row) -> int | None:
    changed = row["position_changed_on"]
    if effective_tier(row) == "pro" or not changed:
        return None
    left = (date.fromisoformat(changed) + timedelta(days=30) - local_today(row)).days
    return left if left > 0 else None


def _quality(item) -> float | None:
    verdict = json.loads(item["verdict"]) if item["verdict"] else {}
    if item["mode"] == "video":
        return verdict["score"] / 10 if "score" in verdict else None
    if item["mode"] == "rush-result" and "averageScore" in verdict:
        return verdict["averageScore"]
    return POINTS.get(item["outcome"])


def _axis(mode: str, puzzle_id: str) -> int | None:
    if mode == "rush-result":
        return 3
    puzzle = PUZZLES.get(puzzle_id) or VIDEOS.get(puzzle_id)
    return puzzle.get("axis") if puzzle else None


def radar_values(row) -> list[float | None]:
    totals, counts = [0.0] * 5, [0] * 5
    for item in attempts_for_radar(row["id"]):
        if item["position"] not in (None, row["primary_position"]):
            continue
        axis, quality = _axis(item["mode"], item["puzzle_id"]), _quality(item)
        if isinstance(axis, int) and 0 <= axis <= 4 and quality is not None:
            totals[axis] += quality
            counts[axis] += 1
    return [round(totals[i] / counts[i], 2) if counts[i] else None for i in range(5)]


def me_payload(row) -> dict:
    pro = effective_tier(row) == "pro"
    today = local_today(row)
    zone = _zone(row["timezone"])
    window = datetime.combine(today - timedelta(days=6), time.min, tzinfo=zone).astimezone(timezone.utc)
    recent = [(_utc(item["created_at"]), item) for item in attempts_since(row["id"], window.strftime(STAMP))]
    history = [
        round(row["overall_elo"] - sum(item["elo_delta"] for at, item in recent if at >= window + timedelta(days=day)))
        for day in range(8)
    ]
    daily_days = {at.astimezone(zone).date() for at, item in recent if item["mode"] == "daily"}
    position = row["primary_position"]
    daily = None
    if position:
        puzzle, mirrored = _daily_for(position, today)
        daily = {"sceneId": to_client(puzzle["target_positions"][0]), "mirrored": mirrored}
    stats = player_stats(row["id"])
    left = {
        mode: None if pro else max(0, limit - count_today(row, MODE_ROWS[mode])) for mode, limit in FREE_LIMITS.items()
    }
    return {
        "id": row["id"],
        "name": display_name(row),
        "email": row["email"],
        "provider": row["provider"],
        "position": to_client(position),
        "positionLockDays": lock_days(row),
        "region": REGION_NAMES.get(row["country"]),
        "coach": coach_of(row),
        "isPro": pro,
        "elo": round(row["overall_elo"]),
        "positionElo": {to_client(key): value for key, value in json.loads(row["position_elo"] or "{}").items()},
        "eloHistory": history,
        "radar": radar_values(row),
        "streak": visible_streak(row["streak_count"] or 0, row["last_daily_on"], today),
        "streakWeek": [today - timedelta(days=6 - offset) in daily_days for offset in range(7)],
        "dailyDone": row["last_daily_on"] == today.isoformat(),
        "daily": daily,
        "rushBest": stats["rush_best"] or 0,
        "attemptsLeft": {"polygon": None, **left},
        "sessionsCount": stats["sessions"],
    }


def attempt_out(row) -> dict:
    verdict = json.loads(row["verdict"]) if row["verdict"] else {}
    mode = {"daily": "polygon", "rush-result": "rush"}.get(row["mode"], row["mode"])
    puzzle = PUZZLES.get(row["puzzle_id"]) or VIDEOS.get(row["puzzle_id"]) or {}
    title = puzzle.get("title", row["puzzle_id"])
    if mode == "rush":
        title = f"Серия {verdict.get('solved', 0)} из {verdict.get('total', 0)}"
    return {
        "id": row["id"],
        "mode": mode,
        "position": to_client(row["position"]),
        "title": title,
        "at": _iso(row["created_at"]),
        "eloDelta": row["elo_delta"],
        "axis": _axis(row["mode"], row["puzzle_id"]),
        "daily": row["mode"] == "daily",
        "outcome": None if mode == "video" else row["outcome"],
        "score": verdict.get("score") if mode == "video" else None,
        "review": verdict.get("review") if mode == "video" else None,
    }


# --- вход и аккаунт ---


class GoogleIn(Body):
    idToken: Long


class AppleIn(Body):
    identityToken: Long
    authorizationCode: Long | None = None
    givenName: Short | None = None
    familyName: Short | None = None


class RefreshIn(Body):
    refreshToken: Short


def _session(access: str, refresh: str, row, offset: str | None) -> dict:
    return {"accessToken": access, "refreshToken": refresh, "user": me_payload(_with_offset(row, offset))}


@router.post("/auth/google")
def auth_google(
    body: GoogleIn, _: None = Depends(limit_ip), x_timezone_offset: str | None = Header(default=None)
) -> dict:
    claims = verify_identity("google", body.idToken)
    return _session(*login_provider("google", claims["sub"], claims.get("email"), None), x_timezone_offset)


@router.post("/auth/apple")
def auth_apple(
    body: AppleIn, _: None = Depends(limit_ip), x_timezone_offset: str | None = Header(default=None)
) -> dict:
    claims = verify_identity("apple", body.identityToken)
    name = " ".join(part.strip() for part in (body.givenName, body.familyName) if part and part.strip())[:20].strip()
    valid = len(name) >= 2 and name.isprintable()
    access, refresh, row = login_provider("apple", claims["sub"], claims.get("email"), name if valid else None)
    if body.authorizationCode:
        # Refresh-токен Apple нужен только чтобы отозвать вход при удалении аккаунта.
        tokens = _apple_call("token", {"code": body.authorizationCode, "grant_type": "authorization_code"})
        if tokens and tokens.get("refresh_token"):
            row = update_user(row["id"], apple_refresh=tokens["refresh_token"])
    return _session(access, refresh, row, x_timezone_offset)


@router.post("/auth/refresh")
def auth_refresh(body: RefreshIn, _: None = Depends(limit_ip)) -> dict:
    pair = refresh_session(body.refreshToken.strip())
    if pair is None:
        raise fail(401, "unauthorized", "Нужно войти заново")
    return {"accessToken": pair[0], "refreshToken": pair[1]}


@router.post("/auth/logout", status_code=204)
def auth_logout(body: RefreshIn) -> Response:
    logout(body.refreshToken.strip())
    return Response(status_code=204)


@router.delete("/me", status_code=204)
def delete_me(row=Depends(player)) -> Response:
    if row["provider"] == "apple" and row["apple_refresh"]:
        _apple_call("revoke", {"token": row["apple_refresh"], "token_type_hint": "refresh_token"})
    delete_user(row["id"])
    return Response(status_code=204)


# --- профиль ---


class MePatch(Body):
    name: Short | None = None
    position: Short | None = None
    region: Short | None = None
    coach: Short | None = None


@router.get("/me")
def get_me(row=Depends(player)) -> dict:
    return me_payload(row)


@router.patch("/me")
def patch_me(body: MePatch, row=Depends(player)) -> dict:
    fields = {}
    if body.name is not None:
        name = body.name.strip()
        if not 2 <= len(name) <= 20 or not name.isprintable():
            raise invalid("Имя от 2 до 20 символов, без переносов строк")
        fields["display_name"] = name
    if body.region is not None:
        if body.region not in REGIONS:
            raise invalid("Неизвестный регион")
        fields["country"] = REGIONS[body.region]
    if body.coach is not None:
        if body.coach not in COACHES:
            raise invalid("Неизвестный тренер")
        if body.coach != "base" and effective_tier(row) != "pro":
            raise fail(403, "pro_required", "Этот тренер доступен в PRO")
        fields["coach"] = body.coach
    if body.position is not None:
        if body.position not in CLIENT_ROLES:
            raise invalid("Неизвестное амплуа")
        row, opens = set_position(row["id"], CLIENT_ROLES[body.position])
        if opens:
            days = (date.fromisoformat(opens) - local_today(row)).days
            raise fail(403, "position_locked", f"Сменить амплуа можно через {days} дн.", daysLeft=days)
    if fields:
        row = update_user(row["id"], **fields)
    return me_payload(row)


@router.get("/me/attempts")
def my_attempts(limit: int = 30, before: str | None = None, row=Depends(player)) -> dict:
    limit = max(1, min(limit, 100))
    cursor = None
    if before:
        try:
            moment = datetime.fromisoformat(before)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            cursor = moment.astimezone(timezone.utc).strftime(STAMP)
        except ValueError:
            raise invalid("before: дата ISO 8601")
    items = [attempt_out(item) for item in attempts_page(row["id"], limit, cursor)]
    return {"items": items, "nextBefore": items[-1]["at"] if len(items) == limit else None}


@router.post("/me/sync-subscription")
def sync_subscription(row=Depends(player)) -> dict:
    # ponytail: RevenueCat ещё не подключён, PRO включается флагом в базе; спросить RevenueCat API, когда появится ключ
    return me_payload(row)


# --- режимы с лимитом ---


class StartIn(Body):
    puzzleId: Short | None = None


@router.post("/modes/{mode}/start")
def start_mode(mode: str, body: StartIn | None = None, row=Depends(player)) -> dict:
    if mode not in FREE_LIMITS:
        raise fail(404, "not_found", "Нет такого режима")
    position = _position(row)
    puzzle_id = "rush"
    if mode == "video":
        puzzle = VIDEOS.get(body.puzzleId if body else "")
        if puzzle is None or position not in puzzle["target_positions"]:
            raise invalid("Видеозадача не найдена для твоего амплуа")
        puzzle_id = puzzle["id"]
    limit = None if effective_tier(row) == "pro" else FREE_LIMITS[mode]
    try:
        session_id, used = start_session(row["id"], MODE_ROWS[mode], puzzle_id, position, limit)
    except QuotaExceeded:
        raise fail(403, "limit_reached", "Попытки на сегодня закончились. Завтра будут новые или открой PRO")
    return {"sessionId": session_id, "attemptsLeft": None if limit is None else limit - used}


def _session_or_fail(row, session_id: str, mode: str):
    session = session_row(row["id"], session_id)
    if session is None or session["mode"] != MODE_ROWS[mode]:
        raise invalid("Сессия не найдена, начни режим заново")
    return session


def _attempt_reply(session, extra: dict) -> dict:
    fresh = user_row(session["user_id"])
    return {**extra, "eloDelta": session["elo_delta"], "attempt": attempt_out(session), "me": me_payload(fresh)}


# --- задачи 2D ---


class Target(Body):
    x: Coord
    y: Coord


class PolygonIn(Body):
    sceneId: Short
    mirrored: bool = False
    target: Target | None = None
    daily: bool = False


class RushAnswer(Body):
    sceneId: Short
    mirrored: bool = False
    target: Target | None = None


class RushIn(Body):
    sessionId: Short
    # за 3 минуты больше сотни сцен не решить
    answers: Annotated[list[RushAnswer], Field(max_length=100)]


def _scene(scene_id: str) -> dict:
    puzzle = SCENES.get(scene_id)
    if puzzle is None:
        raise invalid(f"Неизвестная сцена {scene_id}")
    return puzzle


def _xy(target: Target | None):
    return None if target is None else (target.x, target.y)


@router.post("/attempts/polygon")
def attempt_polygon(body: PolygonIn, row=Depends(player)) -> dict:
    position = _position(row)
    puzzle = _scene(body.sceneId)
    if body.daily:
        daily, mirrored = _daily_for(position, local_today(row))
        if (daily["id"], mirrored) != (puzzle["id"], body.mirrored):
            raise invalid("Это не задача дня")
    target = _xy(body.target)
    verdict = judge(puzzle, target, body.mirrored)
    updated, delta, attempt_id = commit_polygon(
        row["id"], position, puzzle["difficulty"], score_for(verdict["outcome"]), puzzle["id"],
        None if target is None else target[0], None if target is None else target[1],
        verdict["outcome"], verdict["reason"], body.mirrored, "daily" if body.daily else "polygon",
    )
    return {"reason": verdict["reason"], "eloDelta": delta, "attempt": attempt_out(session_row(row["id"], attempt_id)), "me": me_payload(updated)}


@router.post("/attempts/rush")
def attempt_rush(body: RushIn, row=Depends(player)) -> dict:
    session = _session_or_fail(row, body.sessionId, "rush")
    if session["outcome"] == "start":
        if datetime.now(timezone.utc) > _utc(session["created_at"]) + timedelta(seconds=RUSH_WINDOW):
            raise fail(409, "session_expired", "Время спринта вышло")
        if not body.answers:
            raise invalid("Нет ответов")
        judged, lives = [], RUSH_LIVES
        for answer in body.answers:
            if lives == 0:
                break  # ответы после третьей ошибки не считаем
            puzzle = _scene(answer.sceneId)
            verdict = judge(puzzle, _xy(answer.target), answer.mirrored)
            if verdict["outcome"] == "error":
                lives -= 1
            judged.append((puzzle, verdict))
        scores = [score_for(verdict["outcome"]) for _, verdict in judged]
        average = sum(scores) / len(scores)
        outcome = "gold" if average >= 0.75 else "silver" if average >= 0.4 else "error"
        summary = {
            "solved": sum(1 for _, verdict in judged if verdict["outcome"] != "error"),
            "total": len(judged),
            "averageScore": average,
            "answers": [{"sceneId": to_client(p["target_positions"][0]), "reason": v["reason"]} for p, v in judged],
        }
        difficulty = round(sum(puzzle["difficulty"] for puzzle, _ in judged) / len(judged))
        session = finish_session(session["id"], difficulty, average, outcome, "rush", None, summary)
    return _attempt_reply(session, {})


# --- видеоразбор ---


class VideoIn(Body):
    sessionId: Short
    puzzleId: Short
    choice: int
    answer: Annotated[str, Field(max_length=2000)]


def video_out(puzzle: dict) -> dict:
    position = puzzle["target_positions"][0]
    return {
        "id": puzzle["id"],
        "position": to_client(position),
        "sceneId": to_client(position),
        "title": puzzle["title"],
        "videoUrl": puzzle.get("video_url"),
        # ponytail: в json кадра доли 0..1, контракт ждёт метры поля 68 × 105
        "options": [{"x": round(o["x"] * 68, 1), "y": round(o["y"] * 105, 1)} for o in puzzle["options"]],
        "chips": puzzle["chips"],
    }


@router.get("/puzzles/video")
def video_puzzle(row=Depends(player)) -> dict:
    position = _position(row)
    pool = [puzzle for puzzle in VIDEOS.values() if position in puzzle["target_positions"]]
    if not pool:
        raise fail(404, "not_found", "Для этого амплуа видеоразборов пока нет")
    return video_out(pool[local_today(row).toordinal() % len(pool)])


@router.post("/attempts/video")
def attempt_video(body: VideoIn, row=Depends(player)) -> dict:
    session = _session_or_fail(row, body.sessionId, "video")
    if session["puzzle_id"] != body.puzzleId:
        raise invalid("Сессия открыта для другого видео")
    puzzle = VIDEOS[body.puzzleId]
    if session["outcome"] == "start":
        if body.choice not in (0, 1, 2):
            raise invalid("choice: 0, 1 или 2")
        answer = body.answer.strip()
        if len(answer) < 10:
            raise invalid("Объясни решение хотя бы в 10 символов")
        coach = coach_of(row)
        letter = "ABC"[body.choice]
        # ponytail: оценка рубрикой по словам, LLM подключить вместо grade()
        graded = grade(puzzle, letter, answer, COACHES[coach])
        review = {"choice": letter, "answer": answer, "checklist": graded["checklist"], "coach": coach, "reply": graded["coach_reply"]}
        summary = {"score": graded["score"], "review": review, "correct": puzzle["correct"]}
        session = finish_session(session["id"], puzzle["difficulty"], graded["score"] / 10, "video", letter, answer, summary)
    stored = json.loads(session["verdict"])
    return _attempt_reply(session, {"score": stored["score"], "review": stored["review"], "correct": stored["correct"]})


# --- рейтинги и лиги ---


def _entry(item, rank: int, me_id: str) -> dict:
    return {
        "id": item["id"],
        "rank": rank,
        "name": display_name(item),
        "position": to_client(item["primary_position"]),
        "elo": round(item["overall_elo"]),
        "region": REGION_NAMES.get(item["country"]),
        "delta": item["last_delta"] or 0,
        "isMe": item["id"] == me_id,
    }


def board(rows, me_id: str, limit: int) -> dict:
    ids = [item["id"] for item in rows]
    mine = ids.index(me_id)
    shown = set(range(min(limit, len(rows)))) | set(range(max(0, mine - 2), min(len(rows), mine + 3)))
    return {
        "players": [_entry(rows[index], index + 1, me_id) for index in sorted(shown)],
        "me": _entry(rows[mine], mine + 1, me_id),
        "total": len(rows),
    }


@router.get("/leaderboards/{scope}")
def leaderboard(scope: str, limit: int = 100, region: str | None = None, row=Depends(player)) -> dict:
    limit = max(1, min(limit, 100))
    rows = board_rows()
    if scope == "regional":
        region = region or REGION_NAMES.get(row["country"])
        if region not in REGIONS:
            raise invalid("Неизвестный регион")
        # Игрок всегда есть в ответе, даже если смотрит чужой регион.
        rows = [item for item in rows if item["country"] == REGIONS[region] or item["id"] == row["id"]]
    elif scope != "global":
        raise fail(404, "not_found", "Нет такой таблицы")
    return board(rows, row["id"], limit)


class LeagueNameIn(Body):
    name: Short


class JoinIn(Body):
    code: Short


class TransferIn(Body):
    userId: Short


def league_out(league, me_id: str) -> dict:
    rows = board_rows(league_member_ids(league["code"]))
    ids = [item["id"] for item in rows]
    owner = next((item for item in rows if item["id"] == league["owner_id"]), None)
    return {
        "id": league["code"],
        "name": league["name"],
        "code": league["code"],
        "membersCount": len(rows),
        "myRank": ids.index(me_id) + 1 if me_id in ids else None,
        "owner": {"id": league["owner_id"], "name": display_name(owner) if owner else None},
    }


def _member_league(league_id: str, row):
    league = league_row(league_id)
    if league is None or row["id"] not in (league_member_ids(league_id) or []):
        raise fail(404, "league_not_found", "Лига не найдена")
    return league


def _owned_league(league_id: str, row):
    league = _member_league(league_id, row)
    if league["owner_id"] != row["id"]:
        raise fail(403, "not_league_owner", "Это может только создатель лиги")
    return league


def _league_name(name: str, row, skip: str | None = None) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 32 or not name.isprintable():
        raise invalid("Название лиги от 1 до 32 символов, без переносов строк")
    if any(item["name"].casefold() == name.casefold() and item["code"] != skip for item in leagues_of(row["id"])):
        raise fail(409, "league_name_taken", "У тебя уже есть лига с таким названием")
    return name


@router.get("/leagues")
def my_leagues(row=Depends(player)) -> list[dict]:
    return [league_out(league, row["id"]) for league in leagues_of(row["id"])]


@router.post("/leagues")
def create_league(body: LeagueNameIn, row=Depends(player)) -> dict:
    name = _league_name(body.name, row)
    while True:
        code = "".join(secrets.choice(LEAGUE_ALPHABET) for _ in range(6))
        if insert_league(code, name, row["id"]):
            return league_out(league_row(code), row["id"])


@router.post("/leagues/join")
def join(body: JoinIn, row=Depends(player)) -> dict:
    code = body.code.strip().upper()
    if not LEAGUE_CODE.fullmatch(code):
        raise invalid("Код лиги: 6 символов")
    if not join_league(row["id"], code):
        raise fail(404, "league_not_found", "Лига с таким кодом не найдена")
    return league_out(league_row(code), row["id"])


@router.get("/leagues/{league_id}/leaderboard")
def league_board(league_id: str, row=Depends(player)) -> dict:
    league = _member_league(league_id, row)
    return board(board_rows(league_member_ids(league["code"])), row["id"], 100)


@router.patch("/leagues/{league_id}")
def rename_league(league_id: str, body: LeagueNameIn, row=Depends(player)) -> dict:
    league = _owned_league(league_id, row)
    update_league(league["code"], name=_league_name(body.name, row, skip=league["code"]))
    return league_out(league_row(league["code"]), row["id"])


@router.post("/leagues/{league_id}/transfer")
def transfer_league(league_id: str, body: TransferIn, row=Depends(player)) -> dict:
    league = _owned_league(league_id, row)
    if body.userId not in league_member_ids(league["code"]):
        raise invalid("Этот игрок не состоит в лиге")
    update_league(league["code"], owner_id=body.userId)
    return league_out(league_row(league["code"]), row["id"])


@router.post("/leagues/{league_id}/leave", status_code=204)
def leave(league_id: str, row=Depends(player)) -> Response:
    league = _member_league(league_id, row)
    if league["owner_id"] == row["id"]:
        raise fail(403, "not_league_owner", "Сначала передай права или удали лигу")
    leave_league(league["code"], row["id"])
    return Response(status_code=204)


@router.delete("/leagues/{league_id}", status_code=204)
def remove_league(league_id: str, row=Depends(player)) -> Response:
    league = _owned_league(league_id, row)
    delete_league(league["code"])
    return Response(status_code=204)
