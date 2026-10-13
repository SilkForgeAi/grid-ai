"""Quick open's file index, find in files, and replace across files."""

from __future__ import annotations

import subprocess

import pytest

from grid.server.projects import ProjectError
from grid.server.search import Query, glob_match, list_files, replace, search


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def greet(name):\n    return 'hello ' + name\n\nGREETING = 'Hello'\n")
    (tmp_path / "src" / "util.py").write_text("def helper():\n    return greet('x')  # greet\n")
    (tmp_path / "README.md").write_text("Say hello.\r\nhello again\r\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("hello")
    (tmp_path / "image.bin").write_bytes(b"\x00\x01hello")
    return tmp_path


def test_list_files_skips_junk(proj):
    files = list_files(proj)["files"]
    assert "src/app.py" in files and "README.md" in files
    assert not any(f.startswith("node_modules") for f in files)
    assert files.index("README.md") < files.index("src/app.py")   # shallow first


def test_list_files_respects_gitignore(proj):
    (proj / ".gitignore").write_text("secret.txt\n")
    (proj / "secret.txt").write_text("hello")
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    files = list_files(proj)["files"]
    assert "secret.txt" not in files and "src/app.py" in files and ".gitignore" in files


def test_glob_match():
    assert glob_match("src/app.py", "*.py")
    assert glob_match("src/app.py", "src")
    assert glob_match("src/deep/x.ts", "src/**/*.ts")
    assert glob_match("x.ts", "**/*.ts")
    assert not glob_match("lib/app.py", "src")
    assert glob_match("a/b.md", "*.{md,txt}")


def test_search_plain_case_word(proj):
    r = search(proj, Query("hello"))
    paths = {x["path"] for x in r["results"]}
    assert paths == {"src/app.py", "README.md"}          # binary + node_modules skipped
    assert r["matches"] == 4                              # case-insensitive by default
    assert search(proj, Query("hello", case=True))["matches"] == 3
    greet = search(proj, Query("greet", word=True))
    assert greet["matches"] == 3                          # not GREETING
    m = search(proj, Query("return", include=["src/app.py"]))["results"][0]["matches"][0]
    assert (m["line"], m["col"], m["length"]) == (2, 5, 6)
    assert m["text"][m["start"]:m["end"]] == "return"


def test_search_regex_and_errors(proj):
    r = search(proj, Query(r"def (\w+)", regex=True))
    assert r["matches"] == 2
    with pytest.raises(ProjectError):
        search(proj, Query("(", regex=True))
    with pytest.raises(ProjectError):
        search(proj, Query("x*", regex=True))   # matches empty
    with pytest.raises(ProjectError):
        search(proj, Query(""))


def test_include_exclude(proj):
    assert {x["path"] for x in search(proj, Query("hello", include=["*.md"]))["results"]} == {"README.md"}
    assert {x["path"] for x in search(proj, Query("hello", exclude=["*.md"]))["results"]} == {"src/app.py"}


def test_long_line_preview_keeps_offsets(proj):
    (proj / "long.txt").write_text("x " * 300 + "NEEDLE" + " y" * 300 + "\n")
    m = search(proj, Query("needle"))["results"][0]["matches"][0]
    assert m["text"][m["start"]:m["end"]] == "NEEDLE" and len(m["text"]) < 260 and m["clipped_left"]


def test_replace_all_keeps_crlf(proj):
    r = replace(proj, Query("hello", case=True), "bye")
    assert r["replacements"] == 3 and set(r["files_changed"]) == {"src/app.py", "README.md"}
    assert (proj / "README.md").read_bytes() == b"Say bye.\r\nbye again\r\n"
    assert "GREETING = 'Hello'" in (proj / "src" / "app.py").read_text()


def test_replace_regex_groups(proj):
    replace(proj, Query(r"def (\w+)\((\w*)\)", regex=True), "def $1_v2($2)")
    assert "def greet_v2(name):" in (proj / "src" / "app.py").read_text()
    assert "def helper_v2():" in (proj / "src" / "util.py").read_text()
    replace(proj, Query("GREETING", case=True), "$1 costs $$5")          # literal mode: no expansion
    assert "$1 costs $$5 = 'Hello'" in (proj / "src" / "app.py").read_text()


def test_replace_only_one_match_and_stale_skips(proj):
    q = Query("greet", word=True)
    hit = next(x for x in search(proj, q)["results"] if x["path"] == "src/util.py")["matches"][1]
    r = replace(proj, q, "wave", only=[{"path": "src/util.py", "line": hit["line"], "col": hit["col"], "match": hit["match"]}])
    assert r["replacements"] == 1
    assert (proj / "src" / "util.py").read_text() == "def helper():\n    return greet('x')  # wave\n"
    # same request again: that match is gone, so nothing changes
    r = replace(proj, q, "wave", only=[{"path": "src/util.py", "line": hit["line"], "col": hit["col"], "match": "greet"}])
    assert r["replacements"] == 0 and r["skipped"] == 1


def test_replace_limited_to_paths(proj):
    r = replace(proj, Query("hello"), "hi", paths=["README.md"])
    assert r["files_changed"] == ["README.md"]
    assert "hello" in (proj / "src" / "app.py").read_text()


def test_replace_refuses_outside_paths(proj):
    with pytest.raises(ProjectError):
        replace(proj, Query("hello"), "hi", paths=["../etc/passwd"])


def test_symlinks_out_of_the_project_are_ignored(proj, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("hello from outside\n")
    (proj / "link.txt").symlink_to(outside)
    assert "link.txt" not in list_files(proj)["files"]
    assert all(x["path"] != "link.txt" for x in search(proj, Query("outside"))["results"])
    replace(proj, Query("hello"), "bye")
    assert outside.read_text() == "hello from outside\n"
    with pytest.raises(ProjectError):
        replace(proj, Query("hello"), "x", only=[{"path": "link.txt", "line": 1, "col": 1, "match": "hello"}])
    assert outside.read_text() == "hello from outside\n"


def test_bad_path_fails_before_anything_is_written(proj):
    before = (proj / "README.md").read_bytes()
    with pytest.raises(ProjectError):
        replace(proj, Query("hello"), "x", paths=["README.md", "../nope.txt"])
    assert (proj / "README.md").read_bytes() == before
    with pytest.raises(ProjectError):
        replace(proj, Query("hello"), "x", only=[{"path": "README.md"}])


def test_editor_offsets_count_utf16(proj):
    (proj / "emoji.txt").write_text("😀 x = 'needle'\n")
    m = search(proj, Query("needle"))["results"][0]["matches"][0]
    assert m["col"] == 8 and m["ecol"] == 9 and m["elength"] == 6
    js_text = m["text"].encode("utf-16-le")
    assert js_text[m["start"] * 2:m["end"] * 2].decode("utf-16-le") == "needle"
    r = replace(proj, Query("needle"), "pin", only=[{"path": "emoji.txt", "line": 1, "col": m["col"], "match": "needle"}])
    assert r["replacements"] == 1 and "'pin'" in (proj / "emoji.txt").read_text()
