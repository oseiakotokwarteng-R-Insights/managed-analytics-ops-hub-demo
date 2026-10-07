"""Live-clock guarantees, tested on a sandbox warehouse and a few real pre-generated days.  Run: python -m pytest tests/test_live.py -q

The dbt build and the dashboard export are replaced by recorders here (they are exercised end to end by the real ticks and by validate_live);
what is tested is the clock logic: what is released, what is loaded, when the clock moves, and what happens when a night fails."""
from __future__ import annotations

import importlib
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from pipeline import config as cfg

REAL_FUTURE = Path(cfg.ROOT / "sources_live")
HIST_END = date(2026, 9, 30)
DAYS = [HIST_END + timedelta(days=i) for i in range(1, 6)]

pytestmark = pytest.mark.skipif(not REAL_FUTURE.exists(), reason="the generated future (sources_live/) is not present")


def copy_future_subset(dst: Path):
    """Five real days of every stream, as the generator wrote them."""
    for rel in ["wms/WH-01", "wms/WH-03", "freight/carrier_a", "freight/carrier_b", "erp/sales_order_line", "erp/sales_order_header", "erp/po_header", "erp/po_line"]:
        for p in sorted((REAL_FUTURE / rel).glob("*")):
            tag = [d for d in DAYS if d.strftime("%Y%m%d") in p.name or d.isoformat() in p.name]
            if tag:
                (dst / rel).mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst / rel / p.name)
    (dst / "_horizon.json").write_text(json.dumps({"horizon_end": str(DAYS[-1])}))


@pytest.fixture()
def live(tmp_path, monkeypatch):
    db = tmp_path / "state" / "w.duckdb"
    db.parent.mkdir()
    sources, future = tmp_path / "src", tmp_path / "future"
    sources.mkdir()
    copy_future_subset(future)
    monkeypatch.setenv("OPS_HUB_DB", str(db))
    monkeypatch.setenv("OPS_HUB_SOURCES", str(sources))
    monkeypatch.setenv("OPS_HUB_FUTURE", str(future))
    for m in [m for m in sys.modules if m == "pipeline" or m.startswith("pipeline.")]:
        sys.modules.pop(m, None)  # re-import so every module sees the sandbox paths
    cfgm = importlib.import_module("pipeline.config")
    lv = importlib.import_module("pipeline.live")
    calls = {"build": [], "export": 0, "fail_build": False}
    build = importlib.import_module("pipeline.build")
    dash = importlib.import_module("pipeline.export.dashboard")

    def fake_build(as_of=None, test=None):
        if calls["fail_build"]:
            raise RuntimeError("dbt exploded")
        calls["build"].append(as_of)

    monkeypatch.setattr(build, "main", fake_build)
    monkeypatch.setattr(dash, "main", lambda: calls.__setitem__("export", calls["export"] + 1))
    monkeypatch.setattr(dash, "write_live", lambda c, r: None)
    lv.write_clock({"history_end": str(HIST_END), "sim_date": str(HIST_END), "launch_real_date": "2026-10-01"})
    return lv, cfgm, calls, sources


def files(root: Path):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def n_runs(db):
    c = duckdb.connect(str(db), read_only=True)
    try:
        return [r[0] for r in c.execute("SELECT as_of FROM raw._load_runs ORDER BY run_id").fetchall()]
    finally:
        c.close()


def test_a_tick_releases_only_files_that_have_arrived(live):
    lv, cfgm, calls, sources = live
    lv.tick(DAYS[0])
    got = files(sources)
    assert got, "nothing was delivered"
    future = files(lv.FUTURE) - {"_horizon.json"}
    assert got < future, "later days must still be held back"
    assert all(DAYS[1].strftime("%Y%m%d") not in f and DAYS[1].isoformat() not in f for f in got), "a file for a later day leaked into the drop folder"
    assert lv.read_clock()["sim_date"] == str(DAYS[0])


def test_catch_up_loads_every_night_in_order_and_builds_once(live):
    lv, cfgm, calls, sources = live
    lv.tick(DAYS[2])
    assert n_runs(cfgm.WAREHOUSE) == DAYS[:3], "each simulated night must be its own nightly run"
    assert calls["build"] == [str(DAYS[2])], "the models are rebuilt once, for the final night"
    assert calls["export"] == 1
    assert lv.read_clock()["sim_date"] == str(DAYS[2])


def test_rerunning_a_finished_night_changes_nothing(live):
    lv, cfgm, calls, sources = live
    lv.tick(DAYS[1])
    before = files(sources)
    out = lv.tick(DAYS[1])
    assert out["status"] == "NOOP" and files(sources) == before and len(n_runs(cfgm.WAREHOUSE)) == 2 and len(calls["build"]) == 1


def test_a_failed_night_does_not_move_the_clock_and_is_simply_run_again(live):
    lv, cfgm, calls, sources = live
    calls["fail_build"] = True
    with pytest.raises(RuntimeError):
        lv.tick(DAYS[1])
    assert lv.read_clock()["sim_date"] == str(HIST_END), "the clock must not move after a failure"
    assert not lv.LOCK.exists(), "the lock must be released after a failure"
    assert lv.recent_runs()[-1]["status"] == "FAILED"
    calls["fail_build"] = False
    lv.tick(DAYS[1])  # the loaded files are already in the registry: the retry only rebuilds
    assert lv.read_clock()["sim_date"] == str(DAYS[1])
    raw = n_runs(cfgm.WAREHOUSE)
    assert raw[-1] == DAYS[1] and lv.recent_runs()[-1]["status"] == "OK"
    c = duckdb.connect(str(cfgm.WAREHOUSE), read_only=True)
    dup = c.execute("SELECT count(*) FROM (SELECT rel_path FROM raw._load_files WHERE status = 'LOADED' GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    c.close()
    assert dup == 0, "a retried night must not load any file twice"


def test_the_clock_refuses_to_run_past_the_generated_future(live):
    lv, cfgm, calls, sources = live
    with pytest.raises(SystemExit, match="beyond the generated future"):
        lv.tick(DAYS[-1] + timedelta(days=1))
    assert lv.read_clock()["sim_date"] == str(HIST_END)


def test_two_ticks_cannot_run_at_once(live):
    lv, cfgm, calls, sources = live
    lv.LOCK.write_text("999 busy")
    with pytest.raises(SystemExit, match="another tick is running"):
        lv.tick(DAYS[0])
    lv.LOCK.unlink()


def test_todays_target_follows_the_real_calendar(live, monkeypatch):
    lv, cfgm, calls, sources = live
    c = lv.read_clock()
    c["launch_real_date"] = str(lv.now().date() - timedelta(days=3))
    assert lv.target_for_today(c) == HIST_END + timedelta(days=3)
