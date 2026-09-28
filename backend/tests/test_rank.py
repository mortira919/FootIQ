import unittest

from app.rank import rank_for


class RankTests(unittest.TestCase):
    def test_ladder_from_start(self):
        self.assertEqual(rank_for(800), "Новичок")
        self.assertEqual(rank_for(899), "Новичок")
        self.assertEqual(rank_for(900), "Любитель")
        self.assertEqual(rank_for(1899), "Профи")
        self.assertEqual(rank_for(1900), "UEFA Pro")


if __name__ == "__main__":
    unittest.main()
