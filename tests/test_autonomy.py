import pytest

from grid.autonomy import AutonomyPolicy, PendingItem, describe_mode, parse_allow
from grid.rules import classify_command
from grid.tiers import GridTier
from grid.verify import declared_verify_command, trivial_check_reason


def test_parse_allow_validates():
    assert parse_allow(["push", "delete,publish"]) == {"push", "delete", "publish"}
    with pytest.raises(ValueError, match="never be pre-approved"):
        parse_allow(["credentials"])
    with pytest.raises(ValueError, match="unknown category"):
        parse_allow(["everything"])


def test_policy_runs_non_red_and_allowed_red_only():
    p = AutonomyPolicy(frozenset({"push"}))
    assert p.decide([PendingItem("$ pip install x", GridTier.YELLOW)])[0]
    assert not p.decide([PendingItem("$ ???", GridTier.UNKNOWN)])[0]
    assert p.decide([PendingItem("$ git push", GridTier.RED, frozenset({"push"}))])[0]
    ok, why = p.decide([PendingItem("$ git push && rm -rf x", GridTier.RED, frozenset({"push", "delete"}))])
    assert not ok and "--allow delete" in why[0]


def test_hard_blocked_never_runs_even_if_everything_allowed():
    everything = parse_allow(["delete", "git-history", "push", "publish", "deploy",
                              "network-exec", "permissions", "model-flagged"])
    p = AutonomyPolicy(everything)
    for cmd in ["sudo ls", "cat ~/.ssh/id_rsa", "echo x > /etc/hosts", "crontab -e"]:
        v = classify_command(cmd, "/home/me/proj")
        ok, _ = p.decide([PendingItem(cmd, v.tier, frozenset(v.categories))])
        assert not ok, cmd


def test_model_flagged_red_needs_its_own_allow():
    item = PendingItem("$ weird", GridTier.RED)  # no rule category -> model-flagged
    assert not AutonomyPolicy().decide([item])[0]
    assert AutonomyPolicy(frozenset({"model-flagged"})).decide([item])[0]


def test_describe_mode_mentions_verification():
    assert "check" in describe_mode(frozenset())


def test_declared_verify_command():
    assert declared_verify_command("Done.\nVERIFY: `python check.py`") == "python check.py"
    assert declared_verify_command("**VERIFY:** pytest -q tests/test_x.py") == "pytest -q tests/test_x.py"
    assert declared_verify_command("no check here") is None


@pytest.mark.parametrize("cmd", ["true", "echo ok", "exit 0", "pytest || true", "ls", "python -c 'pass'",
                                 "npm test; exit 0", ""])
def test_trivial_checks_refused(cmd):
    assert trivial_check_reason(cmd)


@pytest.mark.parametrize("cmd", ["python -m pytest -q", "python check_add.py", "node test.js", "make test"])
def test_real_checks_accepted(cmd):
    assert trivial_check_reason(cmd) is None
