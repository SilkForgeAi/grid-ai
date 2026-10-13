import pytest

from grid.enforcement import effective_risk_value as eff


def test_high_confidence_leaves_risk_unchanged():
    assert eff("LOW", 0.95) == "LOW"
    assert eff("MEDIUM", 0.95) == "MEDIUM"
    assert eff("HIGH", 0.95) == "HIGH"


def test_low_confidence_escalates_low_to_medium():
    assert eff("LOW", 0.3) == "MEDIUM"


def test_low_confidence_medium_escalates_only_when_strict():
    assert eff("MEDIUM", 0.2, strict=False) == "MEDIUM"
    assert eff("MEDIUM", 0.2, strict=True) == "HIGH"


def test_high_never_escalates_or_lowers():
    assert eff("HIGH", 0.0) == "HIGH"
    assert eff("HIGH", 1.0) == "HIGH"


def test_unknown_stays_unknown():
    assert eff("UNKNOWN", 0.1) == "UNKNOWN"
    assert eff("UNKNOWN", 0.99) == "UNKNOWN"


def test_missing_confidence_default_keeps_base():
    assert eff("LOW", None) == "LOW"


def test_missing_confidence_escalates_when_configured():
    assert eff("LOW", None, escalate_on_missing=True) == "MEDIUM"
    # only LOW is nudged; MEDIUM/HIGH unaffected by the missing-nudge
    assert eff("MEDIUM", None, escalate_on_missing=True) == "MEDIUM"


def test_unrecognized_risk_escalates_to_high():
    with pytest.warns(UserWarning, match="CRITICAL"):
        assert eff("CRITICAL", 0.99) == "HIGH"
    with pytest.warns(UserWarning, match="CRITICAL"):
        assert eff("CRITICAL", None) == "HIGH"


def test_threshold_boundary():
    # exactly at threshold is NOT low (is_low uses strict <)
    assert eff("LOW", 0.6, threshold=0.6) == "LOW"
    assert eff("LOW", 0.59, threshold=0.6) == "MEDIUM"
