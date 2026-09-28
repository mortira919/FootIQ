import unittest

from app.radar import radar


class RadarTests(unittest.TestCase):
    def test_empty_attempts_are_all_zeros(self):
        result = radar("dm", [])
        self.assertEqual([axis["index"] for axis in result["axes"]], [0, 1, 2, 3, 4])
        self.assertEqual([axis["value"] for axis in result["axes"]], [0, 0, 0, 0, 0])

    def test_one_gold_on_axis_one(self):
        result = radar("cb", [{"axis": 1, "outcome": "gold", "mode": "daily"}])
        self.assertEqual([axis["value"] for axis in result["axes"]], [0, 100, 0, 0, 0])

    def test_video_score_five_on_axis_four(self):
        result = radar("dm", [{"axis": 4, "outcome": "video", "score": 5}])
        self.assertEqual(result["axes"][4]["value"], 50)
        self.assertEqual(result["axes"][4]["label"], "Обоснования")
        self.assertEqual([axis["value"] for axis in result["axes"][:4]], [0, 0, 0, 0])

    def test_unknown_position_uses_generic_labels(self):
        result = radar("unknown", [])
        labels = [axis["label"] for axis in result["axes"]]
        self.assertEqual(len(result["axes"]), 5)
        self.assertEqual(labels[:3], ["Позиционирование", "Выбор действия", "Чтение игры"])
        self.assertEqual(labels[3:], ["Скорость решений", "Обоснования"])

    def test_dm_and_cb_labels(self):
        dm = [axis["label"] for axis in radar("dm", [])["axes"]]
        cb = [axis["label"] for axis in radar("cb", [])["axes"]]
        self.assertEqual(dm, ["Прикрытие зоны", "Открывание", "Продвижение", "Скорость решений", "Обоснования"])
        self.assertEqual(cb, ["Линия обороны", "Выбор дуэли", "Выход с мячом", "Скорость решений", "Обоснования"])

    def test_start_and_missing_axis_are_skipped(self):
        attempts = [
            {"axis": 1, "outcome": "start"},
            {"outcome": "gold"},
            {"axis": None, "outcome": "gold"},
            {"axis": 1, "outcome": "silver"},
            {"axis": 1, "outcome": "error"},
        ]
        result = radar("dm", attempts)
        self.assertEqual(result["axes"][1]["value"], 25)


if __name__ == "__main__":
    unittest.main()
