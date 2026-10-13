import pytest

from grid.checkpoints import CheckpointError, CheckpointStore


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    w = tmp_path / "proj"
    w.mkdir()
    (w / "a.py").write_text("one\n")
    return w


def test_snapshot_skips_unchanged_and_restores(ws):
    s = CheckpointStore(ws)
    c0 = s.snapshot("start")
    assert c0 is not None and s.snapshot("again") is None
    (ws / "a.py").write_text("two\n")
    (ws / "new.py").write_text("created\n")
    c1 = s.snapshot("edit")
    assert c1.id == c0.id + 1
    target, before = s.restore(c0.id)
    assert (ws / "a.py").read_text() == "one\n"
    assert not (ws / "new.py").exists()          # created after the target -> removed
    s.restore(before.id)                          # undo the undo
    assert (ws / "a.py").read_text() == "two\n" and (ws / "new.py").exists()


def test_ignored_and_untracked_files_survive_restore(ws):
    (ws / ".gitignore").write_text("secret.txt\n")
    s = CheckpointStore(ws)
    c0 = s.snapshot("start")
    (ws / "secret.txt").write_text("keep me")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "x.js").write_text("x")
    s.restore(c0.id)
    assert (ws / "secret.txt").exists() and (ws / "node_modules" / "x.js").exists()


def test_does_not_touch_users_git_repo(ws):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    s = CheckpointStore(ws)
    s.snapshot("start")
    out = subprocess.run(["git", "status", "--porcelain"], cwd=ws, capture_output=True, text=True).stdout
    assert "a.py" in out  # still untracked in the user's repo: nothing was committed there
    log = subprocess.run(["git", "log"], cwd=ws, capture_output=True, text=True)
    assert log.returncode != 0  # user's repo still has no commits


def test_diff_and_changed_files(ws):
    s = CheckpointStore(ws)
    c0 = s.snapshot("start")
    (ws / "a.py").write_text("two\n")
    assert any("a.py" in line for line in s.changed_files(c0.sha))
    assert "+two" in s.diff(c0.sha)


def test_marks_and_last_good(ws):
    s = CheckpointStore(ws)
    c0 = s.snapshot("start")
    s.mark(c0, tests="1/1 passed", good=True)
    (ws / "a.py").write_text("bad\n")
    c1 = s.snapshot("bad")
    s.mark(c1, tests="0/1 passed", good=False)
    assert s.last_good().id == c0.id
    assert s.get(c1.id).tests == "0/1 passed"


def test_projects_with_same_name_are_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    a = tmp_path / "x" / "api"
    b = tmp_path / "y" / "api"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert CheckpointStore(a).git_dir != CheckpointStore(b).git_dir


def test_refuses_home_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    import os

    with pytest.raises(CheckpointError):
        CheckpointStore(os.path.expanduser("~"))


def test_get_prefers_id_over_sha_prefix(ws):
    s = CheckpointStore(ws)
    cps = []
    for i in range(12):
        (ws / "a.py").write_text(f"v{i}\n")
        cps.append(s.snapshot(f"v{i}"))
    for cp in cps:
        assert s.get(cp.id).id == cp.id
        assert s.get(str(cp.id)).id == cp.id
        assert s.get(cp.sha[:7]).id == cp.id
    assert s.get("#3").id == 3
