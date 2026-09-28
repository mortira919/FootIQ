def elo_delta(player_elo: float, difficulty: int, score: float) -> int:
    puzzle_rating = 700 + 100 * difficulty
    expected = 1 / (1 + 10 ** ((puzzle_rating - player_elo) / 400))
    return round(24 * (score - expected))


def score_for(outcome: str) -> float:
    if outcome == "gold":
        return 1.0
    if outcome == "silver":
        return 0.5
    return 0.0
