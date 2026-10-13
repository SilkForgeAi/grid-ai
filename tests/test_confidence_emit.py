import pytest

from grid.confidence import ConfidenceGate
from grid.confidence_emit import (
    ConfidenceReading,
    parse_action_confidence,
    parse_confidence,
    read_confidence,
)
from grid.tiers import GridTier


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CONFIDENCE: 0.82", 0.82),
        ("confidence = 82%", 0.82),
        ("Confidence:  1", 1.0),
        ("blah\nCONFIDENCE: 0.5\nmore", 0.5),
        ("confidence: 95", 0.95),          # bare >1 treated as percent
    ],
)
def test_parse_confidence_variants(text, expected):
    assert parse_confidence(text) == pytest.approx(expected)


def test_parse_confidence_absent():
    assert parse_confidence("no score here") is None


def test_parse_confidence_last_wins():
    assert parse_confidence("CONFIDENCE: 0.9 ... CONFIDENCE: 0.2") == pytest.approx(0.2)
    assert parse_confidence("CONFIDENCE: 0.9\nCONFIDENCE: 0.2") == pytest.approx(0.2)


def test_reported_line_beats_incidental_assignment():
    text = (
        "Fixing the parser.\n"
        "CONFIDENCE: 0.95\n"
        "I checked calibration.py where `confidence = 0.05` is the default."
    )
    assert parse_confidence(text) == pytest.approx(0.95)
    # A later assignment on its own line is still not the report.
    assert parse_confidence("CONFIDENCE: 0.2\nconfidence = 0.99") == pytest.approx(0.2)


def test_thought_score_beats_reasoning():
    thought = "Fixing the parser.\nCONFIDENCE: 0.2"
    reasoning = "I checked calibration.py where `confidence = 0.99` is the default."
    assert parse_action_confidence(thought, reasoning) == pytest.approx(0.2)
    # Even a second CONFIDENCE line in the reasoning loses to the thought.
    assert parse_action_confidence(thought, "CONFIDENCE: 0.99") == pytest.approx(0.2)


def test_reasoning_is_used_when_thought_has_no_score():
    assert parse_action_confidence("just thinking", "CONFIDENCE: 0.4") == pytest.approx(0.4)


def test_read_confidence_ignores_reasoning_when_thought_has_a_score():
    r = read_confidence(
        "CONFIDENCE: 0.2",
        GridTier.GREEN,
        ConfidenceGate(0.6),
        reasoning="confidence = 0.99",
    )
    assert r is not None
    assert r.score == pytest.approx(0.2)
    assert r.effective_tier is GridTier.YELLOW


def test_parse_confidence_clamped():
    assert parse_confidence("confidence: 1.4") == 1.0


def test_read_confidence_high_keeps_tier():
    r = read_confidence("CONFIDENCE: 0.95", GridTier.GREEN, ConfidenceGate(0.6))
    assert isinstance(r, ConfidenceReading)
    assert r.effective_tier is GridTier.GREEN
    assert r.downgraded is False


def test_read_confidence_low_downgrades_green():
    r = read_confidence("CONFIDENCE: 0.3", GridTier.GREEN, ConfidenceGate(0.6))
    assert r is not None
    assert r.effective_tier is GridTier.YELLOW
    assert r.downgraded is True


def test_read_confidence_red_never_downgraded():
    r = read_confidence("CONFIDENCE: 0.0", GridTier.RED, ConfidenceGate(0.6))
    assert r is not None
    assert r.effective_tier is GridTier.RED
    assert r.downgraded is False


def test_read_confidence_missing_returns_none():
    assert read_confidence("no score", GridTier.GREEN) is None
