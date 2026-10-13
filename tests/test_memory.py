from grid.memory import Episode, MemoryStore


def _store(tmp_path, project="demo"):
    return MemoryStore(project=project, root=tmp_path)


def test_add_and_read_roundtrip(tmp_path):
    s = _store(tmp_path)
    s.add(Episode(error_signature="ImportError on missing package", lesson="pip install it"))
    got = s.all()
    assert len(got) == 1
    assert got[0].error_signature == "ImportError on missing package"
    assert got[0].lesson == "pip install it"


def test_empty_store_is_empty(tmp_path):
    assert _store(tmp_path).all() == []
    assert _store(tmp_path).recent() == []
    assert _store(tmp_path).search("anything") == []
    assert _store(tmp_path).recall_prompt("anything") == ""


def test_recent_orders_newest_first(tmp_path):
    s = _store(tmp_path)
    s.add(Episode(error_signature="old", lesson="a", timestamp=100.0))
    s.add(Episode(error_signature="new", lesson="b", timestamp=200.0))
    recent = s.recent(2)
    assert [e.error_signature for e in recent] == ["new", "old"]


def test_search_scores_by_keyword_overlap(tmp_path):
    s = _store(tmp_path)
    s.add(Episode(error_signature="async await deadlock in handler", lesson="await it"))
    s.add(Episode(error_signature="off by one in loop range", lesson="use <="))
    hits = s.search("why is my async handler hanging")
    assert hits
    assert hits[0].error_signature == "async await deadlock in handler"


def test_search_excludes_zero_overlap(tmp_path):
    s = _store(tmp_path)
    s.add(Episode(error_signature="totally unrelated thing", lesson="x"))
    assert s.search("quantum chromodynamics") == []


def test_recall_prompt_lists_lessons(tmp_path):
    s = _store(tmp_path)
    s.add(Episode(error_signature="missing await on fetch", lesson="await the call", kind="failure"))
    prompt = s.recall_prompt("fetch is returning a coroutine")
    assert "PAST SESSIONS" in prompt
    assert "await the call" in prompt


def test_corrupt_lines_are_skipped(tmp_path):
    s = _store(tmp_path)
    s.add(Episode(error_signature="ok", lesson="fine"))
    with s.path.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")
    assert len(s.all()) == 1


def test_project_slugging_isolates_files(tmp_path):
    a = MemoryStore(project="My Project!", root=tmp_path)
    b = MemoryStore(project="other", root=tmp_path)
    a.add(Episode(error_signature="x", lesson="y"))
    assert a.path.name == "my-project.jsonl"
    assert b.all() == []


def test_search_matches_lesson_text(tmp_path):
    s = _store(tmp_path)
    s.add(Episode(error_signature="build failed",
                  lesson="the Postgres connection pool must be closed in teardown"))
    assert s.search("postgres connection pool")


def test_for_workspace_keys_by_path(tmp_path):
    a, b = tmp_path / "x" / "api", tmp_path / "y" / "api"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    sa = MemoryStore.for_workspace(a, root=tmp_path / "mem")
    sb = MemoryStore.for_workspace(b, root=tmp_path / "mem")
    sa.add(Episode(error_signature="clientA secret layout", lesson="x"))
    assert sa.path != sb.path
    assert sb.all() == []
