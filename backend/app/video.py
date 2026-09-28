import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = ROOT / "puzzles_video"
CAUSAL = ("потому", "чтобы", "значит", "поэтому", "из-за", "так как")
PERSONAS = ("Ассистент", "Пеп", "Жозе", "Юрген")

_REPLIES = {
    "Ассистент": (
        "Решение не держится. Сначала назови, кто закрывает линию паса.",
        "Направление есть, но разбор ещё короткий.",
        "Верно: зона и причина названы.",
    ),
    "Пеп": (
        "Где структура? Покажи, как шаг создаёт численный перегруз.",
        "Близко. Доведи полупространство до конца.",
        "Хорошо. Позиция открыла линию, и команда получила лишнего.",
    ),
    "Жозе": (
        "Слишком рискованно. Сначала компактность, потом вперёд.",
        "Надёжнее, но контратака ещё не собрана.",
        "Дисциплина верная: закрыл линию и не отдал владение.",
    ),
    "Юрген": (
        "Медленно. После потери нужен немедленный шаг вперёд.",
        "Есть вертикаль, не хватает скорости мысли.",
        "Вот так. Вертикально, сразу, без лишнего касания.",
    ),
}


def load_videos() -> dict[str, dict]:
    videos = {}
    if not VIDEO_DIR.exists():
        return videos
    for path in sorted(VIDEO_DIR.glob("*.json")):
        puzzle = json.loads(path.read_text(encoding="utf-8"))
        videos[puzzle["id"]] = puzzle
    return videos


def public_video(puzzle: dict) -> dict:
    return {
        "id": puzzle["id"],
        "target_positions": puzzle["target_positions"],
        "title": puzzle["title"],
        "clip": puzzle["clip"],
        "freeze_ms": puzzle["freeze_ms"],
        "you": puzzle["you"],
        "options": puzzle["options"],
        "chips": puzzle["chips"],
        "difficulty": puzzle["difficulty"],
        "axis": puzzle["axis"],
    }


def grade(puzzle: dict, option: str, text: str, persona: str) -> dict:
    lowered = text.lower()
    points = 0
    checklist = []
    correct = "ABC"[puzzle["correct"]]
    if option == correct:
        points += 3
        checklist.append({"ok": True, "text": f"Вариант {option} — верный"})
    else:
        checklist.append({"ok": False, "text": f"Вариант {option} — неверный, нужен {correct}"})

    role_hits = 0
    for word in puzzle["role_keywords"]:
        if word.lower() in lowered and role_hits < 3:
            role_hits += 1
            checklist.append({"ok": True, "text": f"Зона амплуа: {word}"})
    points += role_hits
    if role_hits == 0:
        checklist.append({"ok": False, "text": "Не сказано про зону ответственности амплуа"})

    factor_hits = 0
    for factor in puzzle["factors"]:
        if factor["root"].lower() in lowered and factor_hits < 2:
            factor_hits += 1
            checklist.append({"ok": True, "text": factor["name"]})
        else:
            checklist.append({"ok": False, "text": f"Упущено: {factor['name']}"})
    points += min(factor_hits, 2)

    causal_hits = min(2, sum(1 for phrase in CAUSAL if phrase in lowered))
    points += causal_hits
    if causal_hits:
        checklist.append({"ok": True, "text": "Есть причинно-следственная связка"})
    else:
        checklist.append({"ok": False, "text": "Нет связки «потому», «чтобы» или «значит»"})

    score = min(10, max(1, points))
    band = 2 if score >= 8 else 1 if score >= 4 else 0
    return {
        "score": score,
        "checklist": checklist,
        "coach_reply": _REPLIES[persona][band],
        "persona": persona,
    }
