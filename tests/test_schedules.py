from datetime import datetime

import pytest

from grid.schedules import Cron, ScheduleError, ScheduleStore


def nxt(expr, at):
    return Cron.parse(expr).next_after(datetime.fromisoformat(at)).isoformat(timespec="minutes")


def test_cron_next():
    assert nxt("*/15 * * * *", "2026-10-10T10:07") == "2026-10-10T10:15"
    assert nxt("0 9 * * 1-5", "2026-10-10T10:00") == "2026-10-12T09:00"     # Sat -> Mon
    assert nxt("@daily", "2026-10-10T23:59") == "2026-10-11T00:00"
    assert nxt("30 2 1 * *", "2026-10-10T00:00") == "2026-11-01T02:30"
    assert nxt("0 0 29 2 *", "2026-03-01T00:00") == "2028-02-29T00:00"
    assert nxt("5/20 * * * *", "2026-10-10T10:06") == "2026-10-10T10:25"
    assert nxt("0 12 * * 0", "2026-10-10T13:00") == "2026-10-11T12:00"       # Sunday
    assert nxt("0 12 * * 7", "2026-10-10T13:00") == "2026-10-11T12:00"       # 7 = Sunday too
    # dom and dow both restricted: either matches (classic cron)
    assert nxt("0 0 13 * 5", "2026-10-10T00:00") == "2026-10-13T00:00"


@pytest.mark.parametrize("bad", ["", "* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *", "a b c d e", "5-1 * * * *"])
def test_cron_rejects(bad):
    with pytest.raises(ScheduleError):
        Cron.parse(bad)


def test_store_add_due_enable(tmp_path):
    store = ScheduleStore(tmp_path / "s")
    proj = tmp_path / "p"
    proj.mkdir()
    s = store.add(name="n", project=str(proj), prompt="do it", cron="0 * * * *",
                  now=datetime.fromisoformat("2026-10-10T10:30"))
    assert datetime.fromtimestamp(s.next_run).isoformat(timespec="minutes") == "2026-10-10T11:00"
    assert store.due(datetime.fromisoformat("2026-10-10T10:59")) == []
    assert [x.id for x in store.due(datetime.fromisoformat("2026-10-10T11:00"))] == [s.id]
    store.set_enabled("n", False)
    assert store.due(datetime.fromisoformat("2026-10-10T12:00")) == []
    with pytest.raises(ScheduleError, match="exists"):
        store.add(name="n", project=str(proj), prompt="x", cron="@daily")
    with pytest.raises(ScheduleError, match="allow only applies"):
        store.add(name="m", project=str(proj), prompt="x", cron="@daily", allow=["push"])
    with pytest.raises(ScheduleError, match="never be pre-approved"):
        store.add(name="m", project=str(proj), prompt="x", cron="@daily", mode="autonomous", allow=["credentials"])
    with pytest.raises(ScheduleError, match="needs a name"):
        store.add(name="  ", project=str(proj), prompt="x", cron="@daily")
    store.remove("n")
    assert store.list() == []
