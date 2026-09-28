import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUZZLE_DIR = ROOT / "puzzles"


def load_puzzles() -> dict[str, dict]:
    puzzles = {}
    for path in sorted(PUZZLE_DIR.glob("*.json")):
        puzzle = json.loads(path.read_text(encoding="utf-8"))
        puzzles[puzzle["id"]] = puzzle
    return puzzles


def for_position(puzzles: dict[str, dict], position: str) -> list[dict]:
    return [puzzle for puzzle in puzzles.values() if position in puzzle["target_positions"]]
