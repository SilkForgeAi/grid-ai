import pytest

from grid.lessons import COMMANDS, expand_lesson
from grid.persona import GRID, TEACHER, PersonaStore, persona_prompt, says_under_18


@pytest.mark.parametrize("text", [
    "I'm 15 years old and want to learn python", "im 13 yo", "I am 16 y/o", "i'm 14.", "I'm 12 and my teacher said",
    "my age is 15", "I'm a 14 year old", "I'm in 8th grade", "i'm in high school", "I am in middle school",
    "I'm a high schooler", "im a 7th grader", "I'm a junior in high school", "I'm 17, can you help?",
])
def test_detects_under_18(text):
    assert says_under_18(text), text


@pytest.mark.parametrize("text", [
    "I'm 15 minutes late", "I'm 25 years old", "I'm 30", "I teach 8th grade", "my son is 12",
    "I'm 3 steps in and stuck", "I'm in college", "I'm a senior engineer", "fix the 12 failing tests",
    "I'm 18", "I'm 10 lines into this function", "I'm 8 hours into this bug",
])
def test_ignores_non_ages(text):
    assert not says_under_18(text), text


def test_default_is_teacher_until_adult_confirmed(tmp_path):
    store = PersonaStore(tmp_path / "p.json")
    p = store.load()
    assert p.effective == TEACHER and p.needs_age_check
    with pytest.raises(PermissionError):
        store.choose(GRID)
    assert store.answer_age("adult").effective == GRID
    assert store.choose(TEACHER).effective == TEACHER
    assert store.choose(GRID).effective == GRID


def test_minor_lock_and_reconfirm(tmp_path):
    store = PersonaStore(tmp_path / "p.json")
    store.answer_age("adult")
    p = store.lock_minor()
    assert p.effective == TEACHER and p.minor_lock and not p.needs_age_check
    with pytest.raises(PermissionError):
        store.choose(GRID)
    assert store.answer_age("adult").effective == GRID   # deliberate re-confirmation in Settings
    with pytest.raises(ValueError):
        store.answer_age("maybe")


def test_prompts():
    grid, teacher = persona_prompt(GRID), persona_prompt(TEACHER)
    assert "roast" in grid and "Profanity is allowed" in grid and "[Grid mode: teacher]" in grid
    assert "No profanity" in teacher and "shit" not in teacher
    for p in (grid, teacher):
        assert "never the human" in p and "professional" in p and "conversation" in p


def test_lesson_commands():
    assert expand_lesson("fix the bug") is None
    assert expand_lesson("/unknown x") is None
    learn = expand_lesson("/learn list comprehensions")
    assert "LESSON MODE" in learn and "list comprehensions" in learn and "Do NOT solve" in learn
    assert "suggest three options" in expand_lesson("/learn")
    assert "not the answer" in expand_lesson("/hint")
    assert "do not fix my code" in expand_lesson("/check")
    assert {c.name for c in COMMANDS} == {"learn", "hint", "check", "next", "solution", "quiz"}
