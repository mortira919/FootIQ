import json
import random
import time
from collections import defaultdict
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path
from pydantic import BaseModel

from app.elo import score_for
from app.geometry import judge
from app.puzzles import for_position, load_puzzles
from app.radar import radar
from app.video import PERSONAS, grade, load_videos, public_video
from app.store import (
    POSITIONS,
    QuotaExceeded,
    attempts_for_radar,
    cached_grade,
    commit_polygon,
    commit_rush,
    commit_video,
    create_league,
    init_db,
    join_league,
    league_member_ids,
    list_attempts,
    login_dev,
    public_user,
    ranking,
    rush_starts_today,
    save_attempt,
    set_country,
    set_position,
    set_tier,
    store_grade,
    user_from_token,
    video_rows_today,
)

STATIC = Path(__file__).resolve().parent / "static"
SITE = Path(__file__).resolve().parent / "site"
PUZZLES = load_puzzles()
VIDEOS = load_videos()
app = FastAPI(title="FootIQ", version="0.2.0")


@app.on_event("startup")
def startup() -> None:
    init_db()


class DevLoginIn(BaseModel):
    name: str


class PositionIn(BaseModel):
    primary_position: str


class TargetIn(BaseModel):
    x: float
    y: float


class ValidateIn(BaseModel):
    puzzle_id: str
    mirrored: bool = False
    target: TargetIn | None = None
    mode: str = "polygon"


class RushAnswerIn(BaseModel):
    puzzle_id: str
    mirrored: bool = False
    target: TargetIn | None = None


class RushIn(BaseModel):
    answers: list[RushAnswerIn]


class VideoAnswerIn(BaseModel):
    puzzle_id: str
    option: str
    text: str
    persona: str = "Ассистент"


class CountryIn(BaseModel):
    country: str


class TierIn(BaseModel):
    tier: str


class LeagueIn(BaseModel):
    name: str


class JoinIn(BaseModel):
    code: str


_hits: dict[str, list[float]] = defaultdict(list)


def _hit(key: str, limit: int) -> None:
    now = time.monotonic()
    recent = [stamp for stamp in _hits[key] if now - stamp < 60]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Слишком много запросов")
    recent.append(now)
    _hits[key] = recent


def limit_ip(request: Request) -> None:
    host = request.client.host if request.client else "unknown"
    _hit("ip:" + host, 20)


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Нужен заголовок Authorization: Bearer <token>")
    row = user_from_token(authorization.removeprefix("Bearer ").strip())
    if row is None:
        raise HTTPException(status_code=401, detail="Сессия не найдена")
    return public_user(row)


def limit_user(request: Request, user: dict = Depends(current_user)) -> dict:
    _hit("user:" + user["id"], 60)
    return user


def _normalize_position(value: str) -> str:
    return value.strip().lower()


def _require_position(user: dict) -> str:
    if not user["primary_position"]:
        raise HTTPException(status_code=400, detail="Сначала выбери primary_position")
    return user["primary_position"]


def _puzzle_or_404(puzzle_id: str) -> dict:
    puzzle = PUZZLES.get(puzzle_id)
    if puzzle is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return puzzle


def _pack(puzzle: dict, mirrored: bool) -> dict:
    payload = dict(puzzle)
    payload["mirrored"] = mirrored
    return payload


@app.get("/stand")
def stand() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# --- сайт: лендинг и страницы, которые требуют сторы ---

app.mount("/assets", StaticFiles(directory=SITE / "assets"), name="assets")


@app.get("/")
def landing() -> FileResponse:
    return FileResponse(SITE / "index.html")


@app.get("/privacy", include_in_schema=False)
def privacy() -> FileResponse:
    return FileResponse(SITE / "privacy.html")


@app.get("/terms", include_in_schema=False)
def terms() -> FileResponse:
    return FileResponse(SITE / "terms.html")


@app.get("/delete", include_in_schema=False)
def delete_account() -> FileResponse:
    return FileResponse(SITE / "delete.html")


@app.get("/l/{code}", include_in_schema=False)
def league_invite(code: str) -> FileResponse:
    return FileResponse(SITE / "league.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "puzzles": len(PUZZLES)}


@app.get("/positions")
def positions() -> dict:
    return {"positions": list(POSITIONS)}


@app.post("/auth/dev-login")
def dev_login(body: DevLoginIn, _: None = Depends(limit_ip)) -> dict:
    try:
        token, row = login_dev(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"access_token": token, "token_type": "bearer", "user": public_user(row)}


@app.get("/users/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user


@app.get("/users/me/attempts")
def my_attempts(user: dict = Depends(current_user)) -> dict:
    return {"attempts": list_attempts(user["id"])}


@app.patch("/users/me/position")
def patch_position(body: PositionIn, user: dict = Depends(limit_user)) -> dict:
    position = _normalize_position(body.primary_position)
    if position not in POSITIONS:
        raise HTTPException(status_code=422, detail="Неизвестное амплуа")
    updated, opens = set_position(user["id"], position)
    if opens:
        raise HTTPException(status_code=403, detail=f"Смена амплуа доступна с {opens}")
    return public_user(updated)


@app.get("/puzzles/next")
def puzzle_next(user: dict = Depends(current_user)) -> dict:
    position = _require_position(user)
    pool = for_position(PUZZLES, position)
    if not pool:
        raise HTTPException(status_code=404, detail="Нет задачи для этого амплуа")
    puzzle = random.choice(pool)
    return _pack(puzzle, random.choice((False, True)))


def _daily_for(position: str, day: date | None = None) -> tuple[dict, bool]:
    pool = []
    for puzzle in sorted(for_position(PUZZLES, position), key=lambda item: item["id"]):
        pool.append((puzzle, False))
        pool.append((puzzle, True))
    if not pool:
        raise HTTPException(status_code=404, detail="Нет задачи дня для этого амплуа")
    return pool[(day or datetime.now(timezone.utc).date()).toordinal() % len(pool)]


@app.get("/puzzles/daily")
def puzzle_daily(user: dict = Depends(current_user)) -> dict:
    position = _require_position(user)
    puzzle, mirrored = _daily_for(position)
    return _pack(puzzle, mirrored)


@app.get("/puzzles/rush/batch")
def puzzle_rush(user: dict = Depends(limit_user)) -> dict:
    position = _require_position(user)
    if rush_starts_today(user["id"]) >= 2:
        raise HTTPException(status_code=403, detail="Лимит Free: 2 спринта в день")
    items = []
    for puzzle in PUZZLES.values():
        own = position in puzzle["target_positions"]
        for mirrored in (False, True):
            items.append((puzzle["difficulty"], 0 if own else 1, puzzle["id"], mirrored, puzzle))
    items.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return {"puzzles": [_pack(item[4], item[3]) for item in items]}


@app.post("/attempts/polygon/validate")
def validate_pass(body: ValidateIn, user: dict = Depends(limit_user)) -> dict:
    position = _require_position(user)
    puzzle = _puzzle_or_404(body.puzzle_id)
    if position not in puzzle["target_positions"]:
        raise HTTPException(status_code=403, detail="Задача не для текущего амплуа")
    target = None if body.target is None else (body.target.x, body.target.y)
    mode = body.mode.strip().lower()
    if mode not in {"polygon", "daily"}:
        raise HTTPException(status_code=422, detail="Режим polygon или daily")
    if mode == "daily":
        daily_puzzle, _mirrored = _daily_for(position)
        if puzzle["id"] != daily_puzzle["id"]:
            raise HTTPException(status_code=403, detail="Это не задача дня")
    verdict = judge(puzzle, target, body.mirrored)
    updated, delta, attempt_id = commit_polygon(
        user["id"],
        position,
        puzzle["difficulty"],
        score_for(verdict["outcome"]),
        puzzle["id"],
        None if target is None else target[0],
        None if target is None else target[1],
        verdict["outcome"],
        verdict["reason"],
        body.mirrored,
        mode,
    )
    return {
        "attempt_id": attempt_id,
        "puzzle_id": puzzle["id"],
        "mirrored": body.mirrored,
        "outcome": verdict["outcome"],
        "reason": verdict["reason"],
        "culprit_number": verdict["culprit_number"],
        "lesson": puzzle["lesson"],
        "elo_delta": delta,
        "overall_elo": updated["overall_elo"],
        "streak_count": public_user(updated)["streak_count"],
    }


@app.post("/attempts/rush")
def finish_rush(body: RushIn, user: dict = Depends(limit_user)) -> dict:
    position = _require_position(user)
    if not body.answers:
        raise HTTPException(status_code=422, detail="Нужен список ответов")
    judged = []
    for answer in body.answers:
        puzzle = _puzzle_or_404(answer.puzzle_id)
        target = None if answer.target is None else (answer.target.x, answer.target.y)
        verdict = judge(puzzle, target, answer.mirrored)
        judged.append((puzzle, verdict))
    scores = [score_for(verdict["outcome"]) for _, verdict in judged]
    average = sum(scores) / len(scores)
    difficulty = round(sum(puzzle["difficulty"] for puzzle, _ in judged) / len(judged))
    if average >= 0.75:
        outcome = "gold"
    elif average >= 0.4:
        outcome = "silver"
    else:
        outcome = "error"
    try:
        updated, delta, attempt_id = commit_rush(user["id"], position, difficulty, average, outcome)
    except QuotaExceeded as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "attempt_id": attempt_id,
        "outcome": outcome,
        "reason": "rush",
        "average_score": average,
        "difficulty": difficulty,
        "elo_delta": delta,
        "overall_elo": updated["overall_elo"],
        "answers": [
            {"puzzle_id": puzzle["id"], "outcome": verdict["outcome"], "reason": verdict["reason"]}
            for puzzle, verdict in judged
        ],
    }


@app.get("/puzzles/video/next")
def video_next(user: dict = Depends(limit_user)) -> dict:
    position = _require_position(user)
    pool = [puzzle for puzzle in VIDEOS.values() if position in puzzle["target_positions"]]
    if not pool:
        raise HTTPException(status_code=404, detail="Нет видеоразбора для этого амплуа")
    started = [
        VIDEOS[row["puzzle_id"]]
        for row in video_rows_today(user["id"], "video-start")
        if row["puzzle_id"] in VIDEOS and position in VIDEOS[row["puzzle_id"]]["target_positions"]
    ]
    if started:
        return public_video(started[0])
    puzzle = pool[0]
    save_attempt(user["id"], puzzle["id"], None, None, "start", "start", False, "video-start", 0)
    return public_video(puzzle)


@app.post("/attempts/video/answer")
def video_answer(body: VideoAnswerIn, user: dict = Depends(limit_user)) -> dict:
    position = _require_position(user)
    puzzle = VIDEOS.get(body.puzzle_id)
    if puzzle is None:
        raise HTTPException(status_code=404, detail="Видеозадача не найдена")
    if position not in puzzle["target_positions"]:
        raise HTTPException(status_code=403, detail="Задача не для текущего амплуа")
    if not any(row["puzzle_id"] == puzzle["id"] for row in video_rows_today(user["id"], "video-start")):
        raise HTTPException(status_code=403, detail="Сначала открой видеоразбор")
    option = body.option.strip().upper()
    if option not in {"A", "B", "C"}:
        raise HTTPException(status_code=422, detail="Вариант должен быть A, B или C")
    text = body.text.strip()
    if len(text) < 10:
        raise HTTPException(status_code=422, detail="Нужно хотя бы 10 символов")
    persona = body.persona if body.persona in PERSONAS else "Ассистент"
    if user.get("subscription_tier", "free") != "pro":
        persona = "Ассистент"
    text_key = " ".join(text.lower().split())
    verdict = cached_grade(puzzle["id"], position, persona, text_key, user["id"])
    cached = verdict is not None
    if verdict is None:
        verdict = grade(puzzle, option, text, persona)
        store_grade(puzzle["id"], position, persona, text_key, user["id"], verdict)
    try:
        updated, delta, attempt_id = commit_video(
            user["id"], position, puzzle["difficulty"], verdict["score"] / 10, puzzle["id"], option, text, verdict
        )
    except QuotaExceeded as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    verdict["elo_delta"] = delta
    return {
        "attempt_id": attempt_id,
        "puzzle_id": puzzle["id"],
        "score": verdict["score"],
        "checklist": verdict["checklist"],
        "coach_reply": verdict["coach_reply"],
        "persona": persona,
        "cached": cached,
        "elo_delta": delta,
        "overall_elo": updated["overall_elo"],
    }


def _attempt_axis(puzzle_id: str) -> int | None:
    puzzle = PUZZLES.get(puzzle_id) or VIDEOS.get(puzzle_id)
    if puzzle is None:
        return None
    axis = puzzle.get("axis")
    return axis if isinstance(axis, int) else None


@app.get("/users/me/radar")
def my_radar(user: dict = Depends(current_user)) -> dict:
    position = _require_position(user)
    packed = []
    for row in attempts_for_radar(user["id"]):
        score = None
        if row["verdict"]:
            score = json.loads(row["verdict"]).get("score")
        packed.append({
            "axis": _attempt_axis(row["puzzle_id"]),
            "outcome": row["outcome"],
            "score": score,
        })
    return radar(position, packed)


@app.patch("/users/me/country")
def patch_country(body: CountryIn, user: dict = Depends(limit_user)) -> dict:
    country = body.country.strip().upper()
    if len(country) != 2:
        raise HTTPException(status_code=422, detail="Страна — две буквы, например KZ")
    return public_user(set_country(user["id"], country))


@app.post("/users/me/tier")
def patch_tier(body: TierIn, user: dict = Depends(limit_user)) -> dict:
    if body.tier not in {"free", "pro"}:
        raise HTTPException(status_code=422, detail="Тариф free или pro")
    return public_user(set_tier(user["id"], body.tier))


@app.get("/leaderboards/{scope}")
def leaderboard(scope: str, user: dict = Depends(current_user), code: str | None = None) -> dict:
    if scope == "global":
        return {"scope": scope, "rows": ranking()}
    if scope == "regional":
        if not user.get("country"):
            raise HTTPException(status_code=400, detail="Сначала укажи страну")
        return {"scope": scope, "rows": ranking(country=user["country"])}
    if scope == "league":
        if not code:
            raise HTTPException(status_code=422, detail="Нужен code")
        members = league_member_ids(code.upper())
        if members is None:
            raise HTTPException(status_code=404, detail="Лига не найдена")
        return {"scope": scope, "rows": ranking(user_ids=members)}
    raise HTTPException(status_code=404, detail="Неизвестный лидерборд")


@app.post("/leagues")
def new_league(body: LeagueIn, user: dict = Depends(limit_user)) -> dict:
    code = create_league(user["id"], body.name.strip())
    return {"code": code, "name": body.name.strip()}


@app.post("/leagues/join")
def enter_league(body: JoinIn, user: dict = Depends(limit_user)) -> dict:
    if not join_league(user["id"], body.code.strip().upper()):
        raise HTTPException(status_code=404, detail="Лига не найдена")
    return {"code": body.code.strip().upper()}



from app import v1  # noqa: E402  (v1 берёт хелперы из этого модуля)

app.include_router(v1.router)
app.add_exception_handler(StarletteHTTPException, v1.http_error)
app.add_exception_handler(RequestValidationError, v1.validation_error)
app.add_exception_handler(Exception, v1.server_error)
