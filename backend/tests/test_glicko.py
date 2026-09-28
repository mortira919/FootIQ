import unittest

from app.glicko import START_R, START_RD, START_SIGMA, puzzle_rating, update_rating


class GlickoTests(unittest.TestCase):
    def test_starting_constants(self):
        self.assertEqual(START_R, 800)
        self.assertEqual(START_RD, 350)
        self.assertEqual(START_SIGMA, 0.06)

    def test_win_against_much_weaker_puzzle_increases_rating(self):
        opponent = puzzle_rating(0)
        new_r, _new_rd, _new_sigma, delta = update_rating(
            START_R, START_RD, START_SIGMA, opponent - 300, 1.0
        )
        self.assertGreater(new_r, START_R)
        self.assertGreater(delta, 0)

    def test_loss_decreases_rating(self):
        new_r, _new_rd, _new_sigma, delta = update_rating(
            START_R, START_RD, START_SIGMA, puzzle_rating(2), 0.0
        )
        self.assertLess(new_r, START_R)
        self.assertLess(delta, 0)

    def test_rd_decreases_after_update(self):
        _new_r, new_rd, _new_sigma, _delta = update_rating(
            START_R, START_RD, START_SIGMA, puzzle_rating(2), 1.0
        )
        self.assertLess(new_rd, START_RD)

    def test_delta_is_int(self):
        _new_r, _new_rd, _new_sigma, delta = update_rating(
            START_R, START_RD, START_SIGMA, puzzle_rating(2), 1.0
        )
        self.assertIsInstance(delta, int)


if __name__ == "__main__":
    unittest.main()
