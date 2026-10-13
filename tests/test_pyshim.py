"""`python` works for Grid's processes on a Mac that only has python3."""

from __future__ import annotations

import os
import shutil
import subprocess

from grid.pyshim import ensure_python_command


def _exe(folder, name, text="#!/bin/sh\necho ok\n"):
    p = folder / name
    p.write_text(text)
    p.chmod(0o755)
    return p


def test_only_python3_gets_a_python(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    bin_ = tmp_path / "usr-bin"
    bin_.mkdir()
    py3 = _exe(bin_, "python3", "#!/bin/sh\necho python3 \"$@\"\n")
    env = {"PATH": str(bin_)}
    added = ensure_python_command(env)
    assert added == str(tmp_path / "home" / "bin")
    assert env["PATH"].split(os.pathsep)[0] == added
    found = shutil.which("python", path=env["PATH"])
    assert found and os.path.realpath(found) == os.path.realpath(py3)
    out = subprocess.run("python -m unittest", shell=True, env=env, capture_output=True, text=True).stdout
    assert out.strip() == "python3 -m unittest"
    # calling again changes nothing
    assert ensure_python_command(env) == added and env["PATH"].count(added) == 1


def test_existing_python_or_no_python_at_all_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    both = tmp_path / "both"
    both.mkdir()
    _exe(both, "python")
    _exe(both, "python3")
    env = {"PATH": str(both)}
    assert ensure_python_command(env) is None and env["PATH"] == str(both)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {"PATH": str(empty)}
    assert ensure_python_command(env) is None and env["PATH"] == str(empty)
