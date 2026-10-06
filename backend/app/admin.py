"""Очередь жалоб и действия модератора (Apple 1.2: снимать нарушающий контент, реагировать в течение 24 часов;
Google UGC: «robust, effective, and ongoing UGC moderation»).

Доступ только по токену ADMIN_TOKEN (секрет сервера) в заголовке Authorization: Bearer <токен>.
Без ADMIN_TOKEN админка выключена. Каждое действие пишется в admin_log.
"""

import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.store import (
    attempt_row,
    delete_league,
    league_row,
    log_admin,
    report_row,
    reports_list,
    reset_name,
    resolve_reports,
    set_ban,
    update_league,
    user_row,
)

SLA_HOURS = 24
router = APIRouter(prefix="/admin")


def moderator(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Админка выключена: не задан ADMIN_TOKEN")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not given or not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="Нужен токен модератора")


def _user_name(row) -> str:
    from app.v1 import display_name  # v1 импортирует store; здесь только имя для очереди

    return display_name(row)


def _current(report) -> dict:
    """Что сейчас лежит на месте цели: модератор видит и снимок на момент жалобы, и текущее состояние."""
    kind, target_id = report["target_type"], report["target_id"]
    if kind == "user":
        row = user_row(target_id)
        return {"exists": row is not None, "name": _user_name(row) if row else None, "banned": bool(row and row["banned_at"])}
    if kind == "league":
        league = league_row(target_id)
        return {"exists": league is not None, "name": league["name"] if league else None, "ownerId": league["owner_id"] if league else None}
    attempt = attempt_row(target_id)
    review = json.loads(attempt["verdict"] or "{}").get("review") if attempt else None
    return {"exists": attempt is not None, "review": review}


def _age_hours(stamp: str) -> float:
    created = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - created).total_seconds() / 3600, 1)


@router.get("/reports", dependencies=[Depends(moderator)])
def queue(status: str = "open") -> dict:
    rows = reports_list(None if status == "all" else status)
    items = []
    for report in rows:
        age = _age_hours(report["created_at"])
        items.append(
            {
                "id": report["id"],
                "targetType": report["target_type"],
                "targetId": report["target_id"],
                "targetOwnerId": report["target_owner_id"],
                "reporterId": report["reporter_id"],
                "reason": report["reason"],
                "comment": report["comment"],
                "snapshot": report["snapshot"],
                "current": _current(report),
                "status": report["status"],
                "resolution": report["resolution"],
                "createdAt": report["created_at"].replace(" ", "T") + "Z",
                "ageHours": age,
                "overdue": report["status"] == "open" and age >= SLA_HOURS,
            }
        )
    return {"items": items, "overdue": sum(item["overdue"] for item in items), "slaHours": SLA_HOURS}


class ResolveIn(BaseModel):
    resolution: str = Field(pattern="^(dismissed|actioned)$")
    note: str | None = Field(default=None, max_length=500)


@router.post("/reports/{report_id}/resolve", dependencies=[Depends(moderator)])
def resolve(report_id: str, body: ResolveIn) -> dict:
    if report_row(report_id) is None:
        raise HTTPException(status_code=404, detail="Жалоба не найдена")
    resolve_reports("id = ?", (report_id,), body.resolution)
    log_admin("resolve_report", "report", report_id, json.dumps({"resolution": body.resolution, "note": body.note}, ensure_ascii=False))
    return {"resolved": report_id}


def _user_or_404(user_id: str):
    row = user_row(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    return row


@router.post("/users/{user_id}/reset-name", dependencies=[Depends(moderator)])
def admin_reset_name(user_id: str) -> dict:
    row = _user_or_404(user_id)
    reset_name(user_id)
    closed = resolve_reports("target_type = 'user' AND target_id = ?", (user_id,), "name_reset")
    log_admin("reset_name", "user", user_id, row["display_name"])
    return {"userId": user_id, "name": _user_name(user_row(user_id)), "reportsResolved": closed}


class BanIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


@router.post("/users/{user_id}/ban", dependencies=[Depends(moderator)])
def ban(user_id: str, body: BanIn) -> dict:
    _user_or_404(user_id)
    set_ban(user_id, body.reason)
    closed = resolve_reports("target_owner_id = ?", (user_id,), "banned")
    log_admin("ban", "user", user_id, body.reason)
    return {"userId": user_id, "banned": True, "reportsResolved": closed}


@router.post("/users/{user_id}/unban", dependencies=[Depends(moderator)])
def unban(user_id: str) -> dict:
    _user_or_404(user_id)
    set_ban(user_id, None)
    log_admin("unban", "user", user_id)
    return {"userId": user_id, "banned": False}


class LeagueRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)


def _league_or_404(league_id: str):
    league = league_row(league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="Лига не найдена")
    return league


@router.patch("/leagues/{league_id}", dependencies=[Depends(moderator)])
def admin_rename_league(league_id: str, body: LeagueRenameIn) -> dict:
    league = _league_or_404(league_id)
    update_league(league_id, name=body.name.strip())
    closed = resolve_reports("target_type = 'league' AND target_id = ?", (league_id,), "league_renamed")
    log_admin("rename_league", "league", league_id, json.dumps({"from": league["name"], "to": body.name.strip()}, ensure_ascii=False))
    return {"leagueId": league_id, "name": body.name.strip(), "reportsResolved": closed}


@router.delete("/leagues/{league_id}", dependencies=[Depends(moderator)])
def admin_delete_league(league_id: str) -> dict:
    league = _league_or_404(league_id)
    delete_league(league_id)
    closed = resolve_reports("target_type = 'league' AND target_id = ?", (league_id,), "league_deleted")
    log_admin("delete_league", "league", league_id, league["name"])
    return {"leagueId": league_id, "deleted": True, "reportsResolved": closed}


@router.get("", include_in_schema=False)
def page() -> Response:
    from fastapi.responses import FileResponse
    from pathlib import Path

    return FileResponse(Path(__file__).resolve().parent / "site" / "admin.html", headers={"X-Robots-Tag": "noindex"})
