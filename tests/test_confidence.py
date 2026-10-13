import pytest

from grid.confidence import ConfidenceGate
from grid.tiers import GridTier


def test_high_confidence_leaves_tier_unchanged():
    gate = ConfidenceGate(threshold=0.6)
    assert gate.adjust(GridTier.GREEN, 0.9) is GridTier.GREEN
    assert gate.adjust(GridTier.YELLOW, 0.9) is GridTier.YELLOW


def test_low_confidence_downgrades_green_to_yellow():
    gate = ConfidenceGate(threshold=0.6)
    assert gate.adjust(GridTier.GREEN, 0.3) is GridTier.YELLOW


def test_red_never_softened_even_at_zero_confidence():
    gate = ConfidenceGate(threshold=0.6)
    assert gate.adjust(GridTier.RED, 0.0) is GridTier.RED
    assert gate.adjust(GridTier.RED, 1.0) is GridTier.RED


def test_strict_escalates_low_confidence_yellow_to_red():
    lenient = ConfidenceGate(threshold=0.6, strict=False)
    strict = ConfidenceGate(threshold=0.6, strict=True)
    assert lenient.adjust(GridTier.YELLOW, 0.2) is GridTier.YELLOW
    assert strict.adjust(GridTier.YELLOW, 0.2) is GridTier.RED


def test_labels():
    gate = ConfidenceGate(threshold=0.6)
    assert "sure" in gate.label(0.95)
    assert "guessing" in gate.label(0.2)


def test_bad_inputs_raise():
    with pytest.raises(ValueError):
        ConfidenceGate(threshold=1.5)
    with pytest.raises(ValueError):
        ConfidenceGate().adjust(GridTier.GREEN, 2.0)
