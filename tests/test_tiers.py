from grid.tiers import GridTier, risk_value_from_tier, tier_from_risk_value


def test_risk_value_maps_to_tier():
    assert tier_from_risk_value("LOW") is GridTier.GREEN
    assert tier_from_risk_value("MEDIUM") is GridTier.YELLOW
    assert tier_from_risk_value("HIGH") is GridTier.RED
    assert tier_from_risk_value("UNKNOWN") is GridTier.UNKNOWN


def test_roundtrip_tier_to_risk_value():
    for tier in GridTier:
        assert tier_from_risk_value(risk_value_from_tier(tier)) is tier


def test_unknown_risk_value_raises():
    import pytest

    with pytest.raises(ValueError):
        tier_from_risk_value("CATASTROPHIC")


def test_tier_colors():
    assert GridTier.GREEN.color == "green"
    assert GridTier.RED.color == "red"
