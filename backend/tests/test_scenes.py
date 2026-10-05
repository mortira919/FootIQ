"""Порт test/polygon_test.dart клиента: сервер судит сцены так же, как приложение."""

import unittest

from app.geometry import gold_centroid, judge
from app.puzzles import load_puzzles

PUZZLES = load_puzzles()
BY_ROLE = {puzzle["target_positions"][0]: puzzle for puzzle in PUZZLES.values()}


def freeze(puzzle: dict, index: int) -> tuple[float, float]:
    x, y = puzzle["scene_data"]["mates"][index]["path"][-1]
    return x, y


class ClientScenes(unittest.TestCase):
    def test_every_episode_both_flanks(self):
        for puzzle in PUZZLES.values():
            for mirrored in (False, True):
                with self.subTest(scene=puzzle["id"], mirrored=mirrored):
                    x, y = gold_centroid(puzzle)
                    center = (68 - x if mirrored else x, y)
                    self.assertEqual(judge(puzzle, center, mirrored)["outcome"], "gold")
                    self.assertEqual(judge(puzzle, None, mirrored)["reason"], "timeout")
                    seen = {
                        judge(puzzle, (gx, gy), mirrored)["outcome"]
                        for gx in range(1, 68, 2)
                        for gy in range(1, 105, 2)
                    }
                    self.assertEqual(seen, {"gold", "silver", "error"})

    def test_tactical_traps(self):
        gk, cm, dm, st = BY_ROLE["gk"], BY_ROLE["cm"], BY_ROLE["dm"], BY_ROLE["st"]
        self.assertEqual(judge(gk, freeze(gk, 1))["reason"], "shadow", "CB behind the curved press")
        self.assertEqual(judge(cm, freeze(cm, 5))["reason"], "offside", "striker is past the line")
        self.assertEqual(judge(dm, freeze(dm, 0))["reason"], "shadow", "staying behind the presser")
        self.assertEqual(judge(st, freeze(st, 0))["reason"], "cone", "standing in front of the CB")
        self.assertEqual(judge(gk, (-3, 90))["reason"], "out")

    def test_cone_steps_like_client(self):
        # Точки, где сервер раньше видел конус, а evaluate() клиента нет: сравнение на 1 006 578 точках.
        cases = [("cb", (9.5, 55.5), "safe"), ("am", (18, 35), "safe"), ("st", (19.5, 27.5), "safe"),
                 ("gk", (52, 88.5), "optimal"), ("lm/rm", (39, 20), "optimal")]
        for role, point, reason in cases:
            self.assertEqual(judge(BY_ROLE[role], point)["reason"], reason, role)


if __name__ == "__main__":
    unittest.main()
