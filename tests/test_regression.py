from grid.regression import RegressionDetector, RunResult, parse_pytest_summary


def test_parse_various_summaries():
    assert parse_pytest_summary("=== 3 passed, 1 failed in 0.12s ===") == RunResult(3, 1)
    assert parse_pytest_summary("10 passed in 1.3s") == RunResult(10, 0)
    assert parse_pytest_summary("2 failed, 5 passed") == RunResult(5, 2)
    assert parse_pytest_summary("1 passed, 2 errors") == RunResult(1, 2)


def test_parse_returns_none_for_non_test_output():
    assert parse_pytest_summary("just some log line") is None


def test_no_regression_with_single_run():
    d = RegressionDetector()
    d.record(RunResult(3, 2))
    assert d.is_regression() is False


def test_detects_pass_ratio_drop():
    d = RegressionDetector()
    d.record(RunResult(4, 1))   # 80%
    d.record(RunResult(2, 3))   # 40%
    assert d.is_regression() is True
    assert "Regression" in (d.reason() or "")


def test_detects_more_failures_even_if_ratio_rises():
    d = RegressionDetector()
    # Scope 100 → 109 is within 10%, so these runs are comparable.
    # Ratio rises (80% → 81%) but one more test fails.
    d.record(RunResult(80, 20))
    d.record(RunResult(88, 21))
    assert d.is_regression() is True
    assert "failing tests increased" in (d.reason() or "")


def test_much_wider_run_is_not_compared():
    d = RegressionDetector()
    d.record(RunResult(5, 1))
    d.record(RunResult(20, 3))  # ratio up, failures up, but scope 6 vs 23
    assert d.is_regression() is False


def test_improvement_is_not_regression():
    d = RegressionDetector()
    d.record(RunResult(2, 3))
    d.record(RunResult(5, 0))
    assert d.is_regression() is False
    assert d.reason() is None


def test_record_from_output():
    d = RegressionDetector()
    assert d.record_from_output("noise") is None
    assert d.record_from_output("3 passed, 0 failed") == RunResult(3, 0)
    assert d.latest == RunResult(3, 0)


def test_skipping_failures_is_a_regression():
    d = RegressionDetector()
    d.record_from_output("=== 2 passed, 8 failed in 0.4s ===")
    d.record_from_output("=== 2 passed, 8 skipped in 0.3s ===")
    assert d.is_regression() is True
    reason = d.reason() or ""
    assert "tests executed dropped 10 -> 2" in reason


def test_deselection_is_a_regression():
    d = RegressionDetector()
    d.record_from_output("=== 10 passed in 0.4s ===")
    d.record_from_output("=== 2 passed, 8 deselected in 0.2s ===")
    assert d.is_regression() is True


def test_xfail_instead_of_failure_is_a_regression():
    d = RegressionDetector()
    d.record_from_output("=== 2 passed, 8 failed in 0.4s ===")
    d.record_from_output("=== 2 passed, 8 xfailed in 0.3s ===")
    assert d.latest is not None
    assert d.latest.skipped == 8
    assert d.is_regression() is True


def test_narrower_scope_is_not_compared_and_does_not_poison_baseline():
    d = RegressionDetector()
    d.record_from_output("=== 8 passed, 2 failed in 0.4s ===")
    d.record_from_output("=== 1 passed in 0.1s ===")
    assert d.is_regression() is False
    # The next full-suite run is compared to the first full suite, not to 1/1.
    d.record_from_output("=== 4 passed, 6 failed in 0.4s ===")
    assert d.is_regression() is True


def test_dead_run_after_healthy_is_a_regression():
    samples = [
        "no tests ran in 0.01s",
        "collected 0 items",
        "collected 12 items / 1 error",
        "ERROR: file or directory not found: tests/",
        "INTERNALERROR> Traceback (most recent call last):",
        "============================ no tests ran in 0.01s ============================",
    ]
    for text in samples:
        d = RegressionDetector()
        d.record(RunResult(10, 0))
        result = d.record_from_output(text)
        assert result is not None and result.errored, text
        assert result.collected == 0
        assert d.is_regression() is True, text


def test_dead_run_with_no_prior_success_is_not_a_regression():
    d = RegressionDetector()
    d.record_from_output("collected 0 items")
    assert d.is_regression() is False


def test_collection_header_alone_is_not_a_result():
    assert parse_pytest_summary("collected 5 items") is None


def test_empty_run_has_no_pass_ratio_and_is_not_a_baseline():
    assert RunResult(0, 0).pass_ratio is None
    d = RegressionDetector()
    d.record(RunResult(0, 0))
    d.record(RunResult(9, 1))
    assert d.is_regression() is False
    assert d.reason() is None


def test_prose_is_not_a_test_run():
    assert parse_pytest_summary(
        "I refactored the helper; 12 passed tests still cover it."
    ) is None
    d = RegressionDetector()
    assert d.record_from_output("I refactored the helper; 12 passed tests still cover it.") is None
    assert d.record_from_output("Now 3 failed, 1 passed") is None
    assert d.history == []
    assert d.is_regression() is False


def test_summary_line_beats_traceback_counts():
    out = (
        "E   assert 1 passed == 2\n"
        "===================== 1 failed, 5 passed in 0.4s =====================\n"
    )
    assert parse_pytest_summary(out) == RunResult(5, 1)


def test_last_summary_line_wins():
    out = (
        "=== 1 passed, 9 failed in 0.2s ===\n"
        "=== 9 passed, 1 failed in 0.4s ===\n"
    )
    assert parse_pytest_summary(out) == RunResult(9, 1)


def test_collected_count_sets_scope():
    text = "collected 5 items\n\n=== 4 passed, 1 failed in 0.3s ===\n"
    assert parse_pytest_summary(text) == RunResult(4, 1, collected=5)


def test_warnings_on_the_summary_line_are_ignored():
    assert parse_pytest_summary("=== 10 passed, 2 warnings in 0.4s ===") == RunResult(10, 0)


def test_adding_a_passing_test_is_not_a_regression():
    d = RegressionDetector()
    d.record(RunResult(10, 0))
    d.record(RunResult(11, 0))
    assert d.is_regression() is False
