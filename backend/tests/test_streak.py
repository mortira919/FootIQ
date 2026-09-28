import unittest
from datetime import date

from app.streak import advance_streak, visible_streak


class StreakTests(unittest.TestCase):
    def test_first_day_and_repeat(self):
        today = date(2026, 9, 26)
        count, last = advance_streak(0, None, today)
        self.assertEqual((count, last), (1, "2026-09-26"))
        again, last = advance_streak(count, last, today)
        self.assertEqual(again, 1)

    def test_next_day_grows_and_gap_resets(self):
        count, last = advance_streak(1, "2026-09-26", date(2026, 9, 27))
        self.assertEqual(count, 2)
        count, last = advance_streak(count, last, date(2026, 9, 29))
        self.assertEqual(count, 1)
        self.assertEqual(visible_streak(4, "2026-09-20", date(2026, 9, 26)), 0)
        self.assertEqual(visible_streak(4, "2026-09-25", date(2026, 9, 26)), 4)


if __name__ == "__main__":
    unittest.main()
