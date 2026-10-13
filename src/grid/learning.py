"""Offline starter projects: working code, a small challenge, and real checks."""
from __future__ import annotations

STARTERS = (
    {"id": "tiny-arcade", "title": "Tiny Arcade", "tag": "PLAY WITH LOGIC", "icon": "sparkle",
     "description": "A guessing game with a secret number. Make the rules your own.",
     "concepts": "Variables · conditions · loops", "challenge": "Add a limit of five guesses."},
    {"id": "story-lab", "title": "Story Lab", "tag": "CODE AN ADVENTURE", "icon": "doc",
     "description": "Two paths, one strange planet. Write the next unexpected turn.",
     "concepts": "Functions · dictionaries · choices", "challenge": "Add a third path and its ending."},
    {"id": "pixel-postcard", "title": "Pixel Postcard", "tag": "MAKE SOMETHING COLORFUL", "icon": "pencil",
     "description": "Turn a tiny grid into a colorful SVG you can keep.",
     "concepts": "Lists · loops · coordinates", "challenge": "Change the pattern to draw your initials."},
)

_CODE = {
    "tiny-arcade": '''"""Run with python main.py. Start by changing the secret number."""

def hint(guess, secret):
    if guess < secret:
        return "Try higher!"
    if guess > secret:
        return "Try lower!"
    return "You found it!"


def main():
    secret = 7
    print("Welcome to Tiny Arcade! Guess a number from 1 to 10.")
    while True:
        try:
            guess = int(input("Your guess: "))
        except ValueError:
            print("Type a whole number, like 4.")
            continue
        print(hint(guess, secret))
        if guess == secret:
            break


if __name__ == "__main__":
    main()
''',
    "story-lab": '''"""Run with python main.py. Add a new path to ENDINGS."""

ENDINGS = {
    "forest": "The glowing trees teach your spaceship to dance. You fly home smiling.",
    "cave": "A tiny dragon offers you tea. You have found your new co-pilot.",
}


def ending(choice):
    return ENDINGS.get(choice.strip().lower(), "That path is still a mystery. Try again!")


def main():
    print("You land on a strange planet. Where will you explore?")
    print("Paths: " + ", ".join(ENDINGS))
    print(ending(input("Choose a path: ")))


if __name__ == "__main__":
    main()
''',
    "pixel-postcard": '''"""Run with python main.py, then open postcard.svg to see your art."""
from pathlib import Path

PALETTE = {".": "#101c2c", "x": "#6ee7c2", "o": "#ffba75"}
PATTERN = [".xx.xx.", "xxxxxxx", "xxxxxxx", ".xxxxx.", "..xxx..", "...o..."]


def render(pattern):
    if not pattern or not pattern[0] or any(len(row) != len(pattern[0]) for row in pattern):
        raise ValueError("Use a nonempty rectangular pattern.")
    pixels = []
    for y, row in enumerate(pattern):
        for x, symbol in enumerate(row):
            color = PALETTE[symbol]
            pixels.append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{color}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {len(pattern[0])} {len(pattern)}" '
            'width="420" height="360">' + "".join(pixels) + "</svg>")


if __name__ == "__main__":
    Path("postcard.svg").write_text(render(PATTERN), encoding="utf-8")
    print("Made postcard.svg! Open it to see your art, then change PATTERN and run again.")
''',
}

_TESTS = {
    "tiny-arcade": '''import unittest
from main import hint

class GameTests(unittest.TestCase):
    def test_higher(self):
        self.assertEqual(hint(2, 7), "Try higher!")
    def test_lower(self):
        self.assertEqual(hint(9, 7), "Try lower!")
    def test_winning_guess(self):
        self.assertEqual(hint(7, 7), "You found it!")
''',
    "story-lab": '''import unittest
from main import ENDINGS, ending

class StoryTests(unittest.TestCase):
    def test_every_path_has_its_ending(self):
        for path, text in ENDINGS.items():
            self.assertEqual(ending(path), text)
    def test_spaces_and_capitals(self):
        self.assertEqual(ending(" FOREST "), ENDINGS["forest"])
    def test_unknown_path(self):
        self.assertIn("Try again", ending("moon"))
''',
    "pixel-postcard": '''import unittest
import xml.etree.ElementTree as ET
from main import PATTERN, render

class ArtTests(unittest.TestCase):
    def test_one_rectangle_per_pixel(self):
        root = ET.fromstring(render(PATTERN))
        self.assertEqual(len(root), sum(map(len, PATTERN)))
        self.assertEqual(root.attrib["viewBox"], f"0 0 {len(PATTERN[0])} {len(PATTERN)}")
    def test_invalid_pattern(self):
        for pattern in ([], [""], ["xx", "x"]):
            with self.assertRaises(ValueError):
                render(pattern)
    def test_unknown_color_is_rejected(self):
        with self.assertRaises(KeyError):
            render(["?"])
''',
}


def starter_files(template: str) -> dict[str, str]:
    item = next(item for item in STARTERS if item["id"] == template)
    title, challenge = item["title"], item["challenge"]
    return {
        "main.py": _CODE[template], "test_main.py": _TESTS[template],
        ".gitignore": "__pycache__/\n.venv/\n.pytest_cache/\npostcard.svg\n",
        "README.md": f"# {title}\n\n{item['description']}\n\n"
        "## Your first small win\n\n"
        "1. Open `main.py` and read the short program.\n"
        "2. Run `python main.py` in the project terminal (Python 3). No extra libraries needed.\n"
        f"3. Make it yours: **{challenge}**\n"
        "4. Run `python -m unittest discover -v` to check the existing behavior.\n\n"
        f"You'll explore: {item['concepts']}.\n\n"
        "Ask Grid for a hint, an explanation, or help with one small change. "
        "Review the diff before keeping changes. Checks cover the starting behavior; "
        "add a check for your new feature too. Checkpoints let you return to an earlier version.\n",
        "GRID.md": f"# Learning project: {title}\n\n"
        "Help the learner understand and enjoy building. Start with one small, runnable change. "
        "Explain the relevant concept in plain language and offer a small next experiment. "
        "When asked for a hint, give the hint and wait; do not edit files or reveal the full solution. "
        "Do not install packages or add network services for these starters. "
        "Respect the learner's chosen teaching depth. Never claim checks cover more than they do.\n\n"
        f"First challenge: {challenge}\n\nverify: python -m unittest discover -v\n",
    }
