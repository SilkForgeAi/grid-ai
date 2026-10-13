"""Tests for GridConfirmationPolicy. These require openhands-sdk; skipped if it
isn't installed so the pure-logic suite still runs everywhere."""

import pytest

pytest.importorskip("openhands.sdk.security.risk")

from openhands.sdk.security.risk import SecurityRisk  # noqa: E402

from grid.policy import GridConfirmationPolicy  # noqa: E402


def test_red_always_confirms():
    p = GridConfirmationPolicy(confirm_yellow=False, confirm_unknown=False)
    assert p.should_confirm(SecurityRisk.HIGH) is True


def test_green_never_confirms():
    p = GridConfirmationPolicy()
    assert p.should_confirm(SecurityRisk.LOW) is False


def test_yellow_follows_config():
    assert GridConfirmationPolicy(confirm_yellow=True).should_confirm(SecurityRisk.MEDIUM) is True
    assert GridConfirmationPolicy(confirm_yellow=False).should_confirm(SecurityRisk.MEDIUM) is False


def test_unknown_follows_config():
    assert GridConfirmationPolicy(confirm_unknown=True).should_confirm(SecurityRisk.UNKNOWN) is True
    assert GridConfirmationPolicy(confirm_unknown=False).should_confirm(SecurityRisk.UNKNOWN) is False


def test_red_ignores_yolo():
    # Even with everything relaxed, HIGH still stops. The core safety invariant.
    p = GridConfirmationPolicy(confirm_yellow=False, confirm_unknown=False)
    assert p.should_confirm(SecurityRisk.HIGH) is True
