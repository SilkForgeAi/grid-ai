import shlex
import sys
import threading
import time

from grid.verify import run_verify


def inline(script):
    return shlex.join([sys.executable, '-c', script])


def test_all_skipped_cannot_be_verified(tmp_path):
    result = run_verify(inline("print('1 skipped in 0.01s')"), str(tmp_path))
    assert result.exit_code == 0
    assert not result.ok
    assert result.summary.skipped == 1


def test_failure_summary_cannot_be_verified_by_zero_exit(tmp_path):
    result = run_verify(inline("print('1 failed, 2 passed in 0.01s')"), str(tmp_path))
    assert not result.ok


def test_cancel_stops_check_and_its_child(tmp_path):
    # A descendant would write evidence after cancellation if it survived.
    marker = tmp_path / 'escaped'
    child = f"import time; from pathlib import Path; time.sleep(2); Path({str(marker)!r}).touch()"
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(20)"
    cancel = threading.Event()
    timer = threading.Timer(.5, cancel.set)
    timer.start()
    try:
        result = run_verify(inline(parent), str(tmp_path), cancel=cancel)
    finally:
        timer.cancel()
    assert result.cancelled and not result.ok
    assert result.seconds < 3
    time.sleep(2)
    assert not marker.exists()


def test_timeout_is_not_success(tmp_path):
    result = run_verify(inline('import time; time.sleep(20)'), str(tmp_path), timeout=.1)
    assert result.timed_out and not result.ok


def test_test_evidence_changes_require_review():
    from grid.verify import test_integrity_reason as reason

    header = 'diff --git a/tests/test_calc.py b/tests/test_calc.py\n'
    assert reason(header + '-    assert add(2, 3) == 5\n+    assert True\n')
    assert reason(header + '+@pytest.mark.skip(reason="later")\n')
    assert reason(header + '+    assert add(2, 3) == 5\n') is None
    assert reason('diff --git a/app.py b/app.py\n-assert ready\n') is None
