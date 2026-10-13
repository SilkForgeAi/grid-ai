"""Pure tests for the Green/Yellow/Red decision (no SDK needed).

GridConfirmationPolicy is a thin adapter over should_confirm_for_risk_value, so
exercising this function verifies the actual gate logic everywhere the SDK isn't
installed. The SDK-integration wrapper is covered separately in test_policy.py."""

import pytest

from grid.tiers import should_confirm_for_risk_value as decide


def test_red_always_confirms_regardless_of_flags():
    assert decide("HIGH", confirm_yellow=False, confirm_unknown=False) is True
    assert decide("HIGH", confirm_yellow=True, confirm_unknown=True) is True


def test_green_never_confirms():
    assert decide("LOW") is False


def test_yellow_follows_flag():
    assert decide("MEDIUM", confirm_yellow=True) is True
    assert decide("MEDIUM", confirm_yellow=False) is False


def test_unknown_follows_flag():
    assert decide("UNKNOWN", confirm_unknown=True) is True
    assert decide("UNKNOWN", confirm_unknown=False) is False


def test_unrecognized_risk_always_confirms():
    # A risk level the SDK might add later must stop, even if UNKNOWN is set to auto-run.
    with pytest.warns(UserWarning, match="SOMETHING_NEW"):
        assert decide("SOMETHING_NEW") is True
    with pytest.warns(UserWarning, match="SOMETHING_NEW"):
        assert decide("SOMETHING_NEW", confirm_yellow=False, confirm_unknown=False) is True
