import unittest

from app.video import grade, load_videos


class VideoGradeTests(unittest.TestCase):
    def setUp(self):
        self.puzzle = load_videos()["vid-dm-shadow-1"]

    def test_full_answer_scores_high(self):
        text = "Я опорник, поэтому шаг в сторону уводит меня из тени и открывает линию паса между линий."
        verdict = grade(self.puzzle, "C", text, "Ассистент")
        self.assertGreaterEqual(verdict["score"], 8)
        self.assertTrue(all(item["text"] for item in verdict["checklist"]))
        self.assertTrue(verdict["coach_reply"])

    def test_wrong_option_without_reasons_is_one(self):
        verdict = grade(self.puzzle, "A", "просто побегу вперёд сейчас", "Пеп")
        self.assertEqual(verdict["score"], 1)
        self.assertFalse(verdict["checklist"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
