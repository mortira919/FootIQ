"""Слой /v1 под контракт Flutter-клиента (API.md). Игровая логика общая со стендом."""

import json
import logging
import os
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.responses import JSONResponse, PlainTextResponse
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

import hashlib
import time as clock

from app import apple, llm, notify, review_login, revenuecat
from app.accounts import erase_account
from app.elo import score_for
from app.geometry import judge
from app.moderation import is_harmful, is_offensive
from app.main import PUZZLES, VIDEOS, _daily_for, _hit, limit_ip
from app.radar import POINTS
from app.store import (
    POSITIONS,
    STAMP,
    QuotaExceeded,
    add_block,
    add_report,
    attempt_row,
    blocked_by,
    blocked_ids,
    bind_reviewer,
    cancel_session,
    log_llm,
    mark_reviewer,
    set_ai_consent,
    shared_grade,
    find_rc_user,
    process_rc_event,
    set_subscription,
    store_grade,
    remove_block,
    _zone,
    attempts_for_radar,
    attempts_page,
    attempts_since,
    board_rows,
    commit_polygon,
    count_today,
    delete_league,
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
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "amplua.support@gmail.com")
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
    request: Request,
    authorization: str | None = Header(default=None),
    x_timezone_offset: str | None = Header(default=None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise fail(401, "unauthorized", "Нужно войти заново")
    row = user_from_fresh_token(authorization.removeprefix("Bearer ").strip())
    if row is None:
        raise fail(401, "unauthorized", "Сессия истекла")
    # Забаненному доступно только удаление аккаунта (Apple 5.1.1(v): удалить можно всегда).
    if row["banned_at"] and not (request.method == "DELETE" and request.url.path == "/v1/me"):
        raise fail(403, "account_banned", f"Аккаунт заблокирован за нарушение правил. Вопросы: {SUPPORT_EMAIL}")
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
        "aiConsentAt": _iso(row["ai_consent_at"]) if row["ai_consent_at"] else None,
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
    if claims.get("email") and claims.get("email_verified") is True:
        bind_reviewer("google", claims["sub"], claims["email"])
    return _session(*login_provider("google", claims["sub"], claims.get("email"), None), x_timezone_offset)


@router.post("/auth/apple")
def auth_apple(
    body: AppleIn, _: None = Depends(limit_ip), x_timezone_offset: str | None = Header(default=None)
) -> dict:
    claims = verify_identity("apple", body.identityToken)
    name = " ".join(part.strip() for part in (body.givenName, body.familyName) if part and part.strip())[:20].strip()
    valid = len(name) >= 2 and name.isprintable() and not is_offensive(name)
    access, refresh, row = login_provider("apple", claims["sub"], claims.get("email"), name if valid else None)
    if body.authorizationCode:
        # Refresh-токен Apple нужен, чтобы отозвать вход при удалении аккаунта. Новый код заменяет старый токен.
        token = apple.exchange_code(body.authorizationCode)
        if token:
            row = update_user(row["id"], apple_refresh=token)
    return _session(access, refresh, row, x_timezone_offset)


class ReviewIn(Body):
    login: Short
    password: Short


def review_login_enabled() -> None:
    # Выключенный вход неотличим от несуществующего пути: 404 раньше разбора тела запроса.
    if not review_login.enabled():
        raise fail(404, "not_found", "Not Found")


@router.post("/auth/review", dependencies=[Depends(review_login_enabled)])
def auth_review(
    body: ReviewIn, request: Request, _: None = Depends(limit_ip), x_timezone_offset: str | None = Header(default=None)
) -> dict:
    """Вход по логину и паролю для служебного аккаунта ревьюеров (App Review, Google App access)."""
    host = request.client.host if request.client else "unknown"
    _hit("review-login:" + host, 5)
    if not review_login.credentials_ok(body.login, body.password):
        log.warning("Неудачный вход ревьюера с %s", host)
        raise fail(401, "unauthorized", "Неверный логин или пароль")
    access, refresh, row = login_provider("google", review_login.REVIEW_SUB, review_login.email(), None)
    mark_reviewer(row["id"])
    return _session(access, refresh, user_row(row["id"]), x_timezone_offset)


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
    erase_account(row)
    return Response(status_code=204)


# --- профиль ---


class MePatch(Body):
    name: Short | None = None
    position: Short | None = None
    region: Short | None = None
    coach: Short | None = None
    aiConsent: bool | None = None


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
        if is_offensive(name):
            raise invalid("В имени есть недопустимые слова. Выбери другое")
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
    if body.aiConsent is not None:
        row = set_ai_consent(row["id"], body.aiConsent)
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


def sync_from_revenuecat(user_id: str) -> bool:
    """Сверяет PRO с REST API RevenueCat. False, если RevenueCat не настроен или не ответил: тогда статус не трогаем."""
    subscriber = revenuecat.get_subscriber(user_id)
    if subscriber is None:
        return False
    set_subscription(user_id, revenuecat.pro_until(subscriber))
    return True


@router.post("/me/sync-subscription")
def sync_subscription(row=Depends(player)) -> dict:
    # Клиент зовёт после покупки и «Восстановить покупки», не дожидаясь вебхука.
    if sync_from_revenuecat(row["id"]):
        row = user_row(row["id"])
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
        _require_ai_consent(row)
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


AI_CONSENT_MESSAGE = "Чтобы тренер оценил ответ, нужно согласие на передачу текста ответа ИИ-сервису"


def _require_ai_consent(row) -> None:
    if not row["ai_consent_at"]:
        raise fail(403, "ai_consent_required", AI_CONSENT_MESSAGE)


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
        "options": [{"x": option["x"], "y": option["y"]} for option in puzzle["options"]],
        "chips": puzzle["chips"],
    }


@router.get("/puzzles/video")
def video_puzzle(row=Depends(player)) -> dict:
    position = _position(row)
    pool = [puzzle for puzzle in VIDEOS.values() if position in puzzle["target_positions"]]
    if not pool:
        raise fail(404, "not_found", "Для этого амплуа видеоразборов пока нет")
    return video_out(pool[local_today(row).toordinal() % len(pool)])


ROLE_TITLES = {
    "gk": "вратарь", "cb": "центральный защитник", "rb/lb": "крайний защитник", "dm": "опорный полузащитник",
    "cm": "центральный полузащитник", "am": "атакующий полузащитник", "lm/rm": "крайний полузащитник",
    "lw/rw": "вингер", "st": "центральный нападающий", "ss": "оттянутый нападающий",
}


def _text_key(letter: str, answer: str) -> str:
    """Ключ семантического кэша: выбранный вариант и ответ без регистра, пунктуации и лишних пробелов."""
    words = re.findall(r"[0-9a-zа-яё]+", answer.lower())
    return letter + ":" + hashlib.sha256(" ".join(words).encode()).hexdigest()


def _llm_task(puzzle: dict, letter: str) -> dict:
    return {
        "title": puzzle["title"],
        "situation": puzzle.get("ground_truth", ""),
        "options": puzzle["options"],
        "chosen": letter,
        "correct": "ABC"[puzzle["correct"]],
        "factors": [factor["name"] for factor in puzzle["factors"]],
        "role_hints": puzzle.get("role_keywords", []),
    }


def _safe(graded: dict) -> bool:
    texts = [graded["reply"], *(item["text"] for item in graded["checklist"])]
    return not any(is_harmful(text) for text in texts)


def grade_answer(row, session_id: str, puzzle: dict, letter: str, answer: str, coach: str) -> dict:
    """Оценка ответа: общий кэш, затем LLM, при сбое или недопустимом ответе запасная рубрика grade().

    Возвращает {score, checklist, reply}. Текст ответа игрока в кэш и в журнал не попадает.
    """
    persona = COACHES[coach]
    key = _text_key(letter, answer)
    position = puzzle["target_positions"][0]
    cached = shared_grade(puzzle["id"], position, persona, key)
    if cached is not None:
        if llm.configured():
            log_llm(row["id"], session_id, llm.provider(), "cache", 0)
        return cached
    if llm.configured():
        started = clock.monotonic()
        status = "ok"
        try:
            graded = llm.grade_with_llm(answer, ROLE_TITLES.get(position, position), _llm_task(puzzle, letter), persona)
            if not _safe(graded):
                status, graded = "filtered", None
        except llm.LLMError:
            log.exception("LLM не оценила ответ, беру запасную рубрику")
            status, graded = "error", None
        except Exception:
            log.exception("LLM упала, беру запасную рубрику")
            status, graded = "error", None
        log_llm(row["id"], session_id, llm.provider(), status, int((clock.monotonic() - started) * 1000))
        if graded is not None:
            # В кэш только checklist, reply и score: ответ игрока там не хранится.
            store_grade(puzzle["id"], position, persona, key, row["id"], graded)
            return graded
    fallback = grade(puzzle, letter, answer, persona)
    return {"score": fallback["score"], "checklist": fallback["checklist"], "reply": fallback["coach_reply"]}


@router.post("/attempts/video")
def attempt_video(body: VideoIn, row=Depends(player)) -> dict:
    session = _session_or_fail(row, body.sessionId, "video")
    if session["puzzle_id"] != body.puzzleId:
        raise invalid("Сессия открыта для другого видео")
    if not row["ai_consent_at"]:
        # Согласие отозвали после старта: попытку возвращаем, текст никуда не уходит.
        cancel_session(row["id"], session["id"])
        raise fail(403, "ai_consent_required", AI_CONSENT_MESSAGE)
    puzzle = VIDEOS[body.puzzleId]
    if session["outcome"] == "start":
        if body.choice not in (0, 1, 2):
            raise invalid("choice: 0, 1 или 2")
        answer = body.answer.strip()
        if len(answer) < 10:
            raise invalid("Объясни решение хотя бы в 10 символов")
        coach = coach_of(row)
        letter = "ABC"[body.choice]
        graded = grade_answer(row, session["id"], puzzle, letter, answer, coach)
        # answer всегда текст этого игрока, даже если checklist и reply взяты из кэша чужого разбора.
        review = {"choice": letter, "answer": answer, "checklist": graded["checklist"], "coach": coach, "reply": graded["reply"]}
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


def board(rows, me_id: str, limit: int, hidden: set[str] = frozenset()) -> dict:
    # Игрок без роли ещё в онбординге, клиент не разберёт его строку в таблице.
    rows = [item for item in rows if item["primary_position"] or item["id"] == me_id]
    ids = [item["id"] for item in rows]
    mine = ids.index(me_id)
    shown = set(range(min(limit, len(rows)))) | set(range(max(0, mine - 2), min(len(rows), mine + 3)))
    return {
        # Заблокированных игрок не видит, но места остальных не сдвигаются: ранг это общий факт таблицы.
        "players": [_entry(rows[index], index + 1, me_id) for index in sorted(shown) if rows[index]["id"] not in hidden],
        "me": _entry(rows[mine], mine + 1, me_id),
        "total": len(rows),
    }


@router.get("/leaderboards/{scope}")
def leaderboard(scope: str, limit: int = 100, region: str | None = None, row=Depends(player)) -> dict:
    limit = max(1, min(limit, 100))
    # Служебные участники лиг ревьюера видны только в его лигах.
    rows = [item for item in board_rows() if not item["review_bot"]]
    if scope == "regional":
        region = region or REGION_NAMES.get(row["country"])
        if region not in REGIONS:
            raise invalid("Неизвестный регион")
        # Игрок всегда есть в ответе, даже если смотрит чужой регион.
        rows = [item for item in rows if item["country"] == REGIONS[region] or item["id"] == row["id"]]
    elif scope != "global":
        raise fail(404, "not_found", "Нет такой таблицы")
    return board(rows, row["id"], limit, blocked_ids(row["id"]))


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
    if is_offensive(name):
        raise invalid("В названии лиги есть недопустимые слова. Выбери другое")
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
    return board(board_rows(league_member_ids(league["code"])), row["id"], 100, blocked_ids(row["id"]))


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


@router.delete("/leagues/{league_id}/members/{user_id}", status_code=204)
def kick_member(league_id: str, user_id: str, row=Depends(player)) -> Response:
    league = _owned_league(league_id, row)
    if user_id == row["id"]:
        raise invalid("Себя исключить нельзя: передай права или удали лигу")
    if user_id not in league_member_ids(league["code"]):
        raise fail(404, "not_found", "Этот игрок не состоит в лиге")
    leave_league(league["code"], user_id)
    return Response(status_code=204)


# --- жалобы и блокировки (Apple 1.2, Google UGC и AI-Generated Content) ---

REPORT_TYPES = ("user", "league", "review")
REPORT_REASONS = ("offensive_name", "offensive_league", "harassment", "cheating", "spam", "harmful_ai", "inaccurate_ai", "other")


class ReportIn(Body):
    targetType: Short
    targetId: Short
    reason: Short
    comment: Annotated[str, Field(max_length=500)] | None = None


def _report_target(body: ReportIn, row) -> tuple[str, str]:
    """Проверяет цель жалобы и возвращает (чей контент, снимок контента для модератора)."""
    if body.targetType == "user":
        target = user_row(body.targetId)
        if target is None or not target["provider"]:
            raise fail(404, "not_found", "Игрок не найден")
        if target["id"] == row["id"]:
            raise invalid("Нельзя пожаловаться на себя")
        return target["id"], display_name(target)
    if body.targetType == "league":
        league = league_row(body.targetId)
        if league is None:
            raise fail(404, "not_found", "Лига не найдена")
        return league["owner_id"], league["name"]
    # review: только на свой разбор тренера, чужие попытки для игрока не существуют.
    attempt = attempt_row(body.targetId)
    if attempt is None or attempt["user_id"] != row["id"] or attempt["mode"] != "video" or attempt["outcome"] == "start":
        raise fail(404, "not_found", "Разбор не найден")
    review = (json.loads(attempt["verdict"] or "{}")).get("review") or {}
    return row["id"], review.get("reply") or ""


@router.post("/reports", status_code=204)
def report(body: ReportIn, background: BackgroundTasks, row=Depends(player)) -> Response:
    if body.targetType not in REPORT_TYPES:
        raise invalid("targetType: user, league или review")
    if body.reason not in REPORT_REASONS:
        raise invalid("Неизвестная причина жалобы")
    comment = (body.comment or "").strip() or None
    owner, snapshot = _report_target(body, row)
    if add_report(row["id"], body.targetType, body.targetId, owner, body.reason, comment, snapshot):
        background.add_task(
            notify.send, f"Amplua: новая жалоба ({body.targetType}, {body.reason}) на «{snapshot[:120]}». Разобрать за 24 часа: /admin"
        )
    return Response(status_code=204)


class BlockIn(Body):
    userId: Short


@router.get("/blocks")
def my_blocks(row=Depends(player)) -> list[dict]:
    return [{"id": item["id"], "name": display_name(item), "position": to_client(item["primary_position"])} for item in blocked_by(row["id"])]


@router.post("/blocks", status_code=204)
def block(body: BlockIn, row=Depends(player)) -> Response:
    target = user_row(body.userId)
    if target is None or not target["provider"]:
        raise fail(404, "not_found", "Игрок не найден")
    if target["id"] == row["id"]:
        raise invalid("Нельзя заблокировать себя")
    add_block(row["id"], target["id"])
    return Response(status_code=204)


@router.delete("/blocks/{user_id}", status_code=204)
def unblock(user_id: str, row=Depends(player)) -> Response:
    remove_block(row["id"], user_id)
    return Response(status_code=204)


# --- вебхук RevenueCat ---

# Названия событий по https://www.revenuecat.com/docs/integrations/webhooks/event-types-and-fields
RC_GRANT = {
    "INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "NON_RENEWING_PURCHASE", "PRODUCT_CHANGE",
    "SUBSCRIPTION_EXTENDED", "TEMPORARY_ENTITLEMENT_GRANT", "REFUND_REVERSED",
}
RC_REFUND_REASON = "CUSTOMER_SUPPORT"  # CANCELLATION с этой причиной означает возврат денег


def _rc_date(ms) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _rc_authorized(header: str | None) -> bool:
    secret = os.environ.get("REVENUECAT_WEBHOOK_SECRET")
    if not secret or not header:
        return False
    given = header.strip()
    return any(secrets.compare_digest(given.encode(), value.encode()) for value in (secret, f"Bearer {secret}"))


def _rc_effect(event: dict) -> tuple[str, str | None]:
    """Что событие делает с PRO: ("grant", дата) | ("revoke", None) | ("keep", дата) | ("ignore", None)."""
    kind = event.get("type")
    ids = event.get("entitlement_ids")
    if ids is not None and revenuecat.entitlement() not in ids and kind not in ("EXPIRATION", "CANCELLATION", "TRANSFER"):
        return "ignore", None
    expires = event.get("expiration_at_ms")
    if kind in RC_GRANT:
        return "grant", _rc_date(expires) if expires is not None else revenuecat.LIFETIME
    if kind == "CANCELLATION":
        # Обычная отмена: доступ до конца оплаченного периода. Возврат денег снимает PRO сразу.
        if event.get("cancel_reason") == RC_REFUND_REASON:
            return "revoke", None
        return "keep", _rc_date(expires)
    if kind == "EXPIRATION":
        return "revoke", None
    if kind == "BILLING_ISSUE":
        # Во время grace period стор ещё пытается списать деньги, доступ сохраняется. Без grace ждём EXPIRATION.
        grace = event.get("grace_period_expiration_at_ms")
        return ("keep", _rc_date(grace)) if grace else ("ignore", None)
    return "ignore", None  # TEST, SUBSCRIPTION_PAUSED (пауза с конца периода, потом придёт EXPIRATION) и прочие


@router.post("/webhooks/revenuecat")
async def revenuecat_webhook(request: Request, authorization: str | None = Header(default=None)) -> dict:
    if not _rc_authorized(authorization):
        raise fail(401, "unauthorized", "Неверный секрет вебхука")
    try:
        payload = await request.json()
        event = payload["event"]
        event_id, kind = str(event["id"]), str(event["type"])
    except (ValueError, KeyError, TypeError):
        raise invalid("Ожидается {api_version, event: {id, type, ...}}")

    if kind == "TRANSFER":
        moved_to = [str(item) for item in event.get("transferred_to") or []]
        moved_from = [str(item) for item in event.get("transferred_from") or []]
        target, source = find_rc_user(moved_to), find_rc_user(moved_from)

        def apply(connection):
            # Покупка переехала: у прежнего владельца PRO снимаем, новому переносим срок прежнего.
            if source:
                previous = connection.execute("SELECT pro_until, subscription_tier FROM users WHERE id = ?", (source,)).fetchone()
                set_subscription(source, None, connection)
                if target and previous["subscription_tier"] == "pro":
                    set_subscription(target, previous["pro_until"], connection)

        fresh = process_rc_event(event_id, kind, ",".join(moved_to), target, apply)
        affected = [user for user in (source, target) if user]
    else:
        candidates = [event.get("app_user_id"), event.get("original_app_user_id"), *(event.get("aliases") or [])]
        user_id = find_rc_user([str(item) for item in candidates if item])
        effect, until = _rc_effect(event)

        def apply(connection):
            if user_id is None or effect == "ignore":
                return
            if effect == "revoke":
                set_subscription(user_id, None, connection)
            elif effect == "grant" or (effect == "keep" and until):
                set_subscription(user_id, until, connection)

        fresh = process_rc_event(event_id, kind, event.get("app_user_id"), user_id, apply)
        affected = [user_id] if user_id else []
    if fresh:
        # RevenueCat советует после вебхука сверяться через GET /subscribers: тогда статус всегда в одном формате.
        for user in affected:
            sync_from_revenuecat(user)
    return {"ok": True, "duplicate": not fresh}
