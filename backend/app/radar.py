POINTS = {
    "gold": 1.0,
    "silver": 0.5,
    "error": 0.0,
}

GENERIC = ("Позиционирование", "Выбор действия", "Чтение игры")

ROLE_AXES = {
    "gk": ("Выбор позиции", "Игра на выходах", "Ввод мяча"),
    "cb": ("Линия обороны", "Выбор дуэли", "Выход с мячом"),
    "rb/lb": ("Ширина атаки", "Подстраховка", "Подача"),
    "dm": ("Прикрытие зоны", "Открывание", "Продвижение"),
    "cm": ("Связка линий", "Смена фланга", "Полупространство"),
    "am": ("Между линий", "Последний пас", "Создание момента"),
    "lm/rm": ("Удержание ширины", "Вход внутрь", "Навес"),
    "lw/rw": ("Обыгрыш фланга", "Смещение внутрь", "Подача"),
    "st": ("Движение за спину", "Выбор момента", "Завершение"),
    "ss": ("Связка атаки", "Разворот к воротам", "Игра между линий"),
}

SHARED = ("Скорость решений", "Обоснования")


def _labels(position: str) -> tuple[str, str, str, str, str]:
    role = ROLE_AXES.get((position or "").strip().lower(), GENERIC)
    return role[0], role[1], role[2], SHARED[0], SHARED[1]


def _points(attempt: dict) -> tuple[int, float] | None:
    if attempt.get("outcome") == "start":
        return None
    axis = attempt.get("axis")
    if type(axis) is not int or not 0 <= axis <= 4:
        return None
    outcome = attempt.get("outcome")
    if outcome == "video":
        score = attempt.get("score", 0)
        if type(score) is not int:
            return None
        return axis, score / 10
    if outcome not in POINTS:
        return None
    return axis, POINTS[outcome]


def radar(position: str, attempts: list[dict]) -> dict:
    totals = [0.0, 0.0, 0.0, 0.0, 0.0]
    counts = [0, 0, 0, 0, 0]
    for attempt in attempts:
        scored = _points(attempt)
        if scored is None:
            continue
        axis, points = scored
        totals[axis] += points
        counts[axis] += 1
    axes = []
    for index, label in enumerate(_labels(position)):
        if counts[index]:
            value = int(round(100 * totals[index] / counts[index]))
            value = max(0, min(100, value))
        else:
            value = 0
        axes.append({"index": index, "label": label, "value": value})
    return {"axes": axes}
