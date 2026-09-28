import unittest

from app.geometry import gold_centroid, judge
from app.puzzles import load_puzzles


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.puzzle = load_puzzles()["dm-shadow-1"]

    def test_gold_centroid_is_gold(self):
        verdict = judge(self.puzzle, gold_centroid(self.puzzle))
        self.assertEqual(verdict["reason"], "optimal")

    def test_mirrored_centroid_is_gold(self):
        x, y = gold_centroid(self.puzzle)
        verdict = judge(self.puzzle, (68 - x, y), mirrored=True)
        self.assertEqual(verdict["reason"], "optimal")

    def test_timeout_out_shadow_silver(self):
        self.assertEqual(judge(self.puzzle, None)["reason"], "timeout")
        self.assertEqual(judge(self.puzzle, (80, 10))["reason"], "out")
        self.assertEqual(judge(self.puzzle, (30, 58))["reason"], "shadow")
        self.assertEqual(judge(self.puzzle, (20, 63))["reason"], "safe")


if __name__ == "__main__":
    unittest.main()
