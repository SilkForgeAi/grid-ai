"""SDK-gated test for GridSecurityAnalyzer. Skipped when openhands-sdk (py>=3.12)
isn't installed; the enforcement logic itself is covered purely in
test_enforcement.py."""

import pytest

pytest.importorskip("openhands.sdk.security.analyzer")

from openhands.sdk.security.risk import SecurityRisk  # noqa: E402

from grid.analyzer import GridSecurityAnalyzer  # noqa: E402


class _FakeText:
    def __init__(self, text):
        self.text = text


class _FakeAction:
    """Minimal stand-in for ActionEvent: just the attrs the analyzer reads."""

    def __init__(self, risk, thought_text, reasoning=None):
        self.security_risk = risk
        self.thought = [_FakeText(thought_text)]
        self.reasoning_content = reasoning


def test_low_confidence_escalates_low_to_medium():
    a = _FakeAction(SecurityRisk.LOW, "doing a thing\nCONFIDENCE: 0.3")
    assert GridSecurityAnalyzer().security_risk(a) == SecurityRisk.MEDIUM


def test_high_confidence_keeps_low():
    a = _FakeAction(SecurityRisk.LOW, "CONFIDENCE: 0.95")
    assert GridSecurityAnalyzer().security_risk(a) == SecurityRisk.LOW


def test_high_stays_high_even_when_guessing():
    a = _FakeAction(SecurityRisk.HIGH, "CONFIDENCE: 0.0")
    assert GridSecurityAnalyzer().security_risk(a) == SecurityRisk.HIGH


def test_missing_risk_defaults_unknown():
    a = _FakeAction(None, "CONFIDENCE: 0.9")
    assert GridSecurityAnalyzer().security_risk(a) == SecurityRisk.UNKNOWN
