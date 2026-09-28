import unittest
from datetime import date

from app.position_rule import can_change_position


class PositionRuleTests(unittest.TestCase):
    def test_first_choice_and_pro_are_open(self):
        today = date(2026, 9, 25)
        self.assertTrue(can_change_position(None, "dm", None, today, "free")[0])
        self.assertTrue(can_change_position("dm", "cb", "2026-09-25", today, "pro")[0])

    def test_free_change_waits_thirty_days(self):
        allowed, opens = can_change_position("dm", "cb", "2026-09-25", date(2026, 10, 24), "free")
        self.assertFalse(allowed)
        self.assertEqual(opens, "2026-10-25")
        self.assertTrue(can_change_position("dm", "cb", "2026-09-25", date(2026, 10, 25), "free")[0])
        self.assertTrue(can_change_position("dm", "dm", "2026-09-25", date(2026, 9, 26), "free")[0])


if __name__ == "__main__":
    unittest.main()
