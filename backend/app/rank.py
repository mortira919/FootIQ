RANKS = (
    (900, "Новичок"),
    (1100, "Любитель"),
    (1300, "Игрок"),
    (1500, "Аналитик"),
    (1700, "Тренер"),
    (1900, "Профи"),
    (10**9, "UEFA Pro"),
)


def rank_for(elo: float) -> str:
    for ceiling, title in RANKS:
        if elo < ceiling:
            return title
    return RANKS[-1][1]
