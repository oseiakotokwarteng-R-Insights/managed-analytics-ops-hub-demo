"""Monitor sensitivity tests: do the freshness, volume, duplicate-file and value-format monitors fire on real incidents and stay quiet otherwise?

A 61-day sandbox is cut from real source files, four incidents are injected into otherwise untouched streams, the files are ingested night by night,
and the real ops models (not copies of their logic) are built on that database.  Run: python -m pytest tests/test_monitors.py -q
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from pipeline import config as cfg
from pipeline.ingest.engine import Ingestor

START, END = date(2025, 3, 1), date(2025, 4, 30)
DBT_DIR = cfg.ROOT / "pipeline" / "dbt"
DBT = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
MODELS = ["ops_file_arrival", "freshness_daily", "volume_daily", "duplicate_file_daily", "format_drift_daily"]

# the injected incidents
OUTAGE = {"stream": "wms:WH-01", "first_missing": date(2025, 4, 20), "last_missing": date(2025, 4, 22)}
SPIKE = {"stream": "wms:WH-03", "day": date(2025, 4, 15), "factor": 5}
RESEND = {"stream": "carrier_a_shipments", "name": "shipments_20250425_resend.json", "of": "shipments_20250424.json"}
DRIFT = {"entity": "WH-02", "first_day": date(2025, 4, 26)}


def days(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def build_sources(dst: Path) -> None:
    src = cfg.SOURCES
    for wh in ("WH-01", "WH-02", "WH-03", "WH-04"):
        (dst / "wms" / wh).mkdir(parents=True, exist_ok=True)
        for d in days(START, END):
            s = src / "wms" / wh / f"{d.isoformat()}.jsonl"
            if wh == "WH-01" and OUTAGE["first_missing"] <= d <= OUTAGE["last_missing"]:
                continue  # the warehouse sends nothing
            text = s.read_text(encoding="utf-8")
            if wh == SPIKE["stream"][4:] and d == SPIKE["day"]:
                text = text * SPIKE["factor"]  # a re-publish storm
            if wh == DRIFT["entity"] and d >= DRIFT["first_day"]:
                text = re.sub(r'"bin":"([A-Z])-(\d+)-(\d+)"', lambda m: f'"bin":"{m.group(1)}{int(m.group(2)):02d}-{int(m.group(3)):02d}"', text)
            (dst / "wms" / wh / s.name).write_text(text, encoding="utf-8")
    (dst / "freight" / "carrier_a").mkdir(parents=True, exist_ok=True)
    for d in days(START, END):
        n = f"shipments_{d.strftime('%Y%m%d')}.json"
        shutil.copy2(src / "freight" / "carrier_a" / n, dst / "freight" / "carrier_a" / n)
    shutil.copy2(dst / "freight" / "carrier_a" / RESEND["of"], dst / "freight" / "carrier_a" / RESEND["name"])  # a byte-identical re-send


def dbt(args, env):
    r = subprocess.run([str(DBT), *args, "--profiles-dir", str(DBT_DIR), "--project-dir", str(DBT_DIR), "--vars", f"{{history_start: {START}, history_end: {END}}}"],
                       cwd=DBT_DIR, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1500:]


@pytest.fixture(scope="module")
def mon(tmp_path_factory):
    root = tmp_path_factory.mktemp("monitors")
    sources, db = root / "src", root / "w.duckdb"
    build_sources(sources)
    i = Ingestor(db, sources, None)
    i.backfill(START, END)
    i.close()
    env = {**os.environ, "OPS_HUB_DB": str(db), "DBT_TARGET_PATH": str(root / "target"), "DBT_LOG_PATH": str(root / "logs")}
    dbt(["seed", "--select", "monitor_streams", "closure_days"], env)
    dbt(["run", "--select", *MODELS], env)
    con = duckdb.connect(str(db), read_only=True)
    yield con
    con.close()


def rows(con, sql):
    return con.execute(sql).fetchall()


def test_outage_is_flagged_within_two_days(mon):
    late = rows(mon, f"select as_of from ops.freshness_daily where stream = '{OUTAGE['stream']}' and is_late order by as_of")
    assert late, "a three-day silence on a stock-critical stream raised nothing"
    assert late[0][0] - OUTAGE["first_missing"] <= timedelta(days=2)
    assert late[-1][0] <= OUTAGE["last_missing"] + timedelta(days=1), "the alert should clear once files resume"


def test_volume_spike_is_flagged_on_the_day(mon):
    got = rows(mon, f"select arrival from ops.volume_daily where stream = '{SPIKE['stream']}' and is_anomaly")
    assert [g[0] for g in got] == [SPIKE["day"]]


def test_resent_file_is_flagged_as_a_duplicate(mon):
    got = rows(mon, "select rel_path, duplicate_of from ops.duplicate_file_daily")
    assert len(got) == 1 and got[0][0].endswith(RESEND["name"]) and got[0][1].endswith(RESEND["of"])


def test_value_format_drift_is_flagged_within_three_days(mon):
    got = rows(mon, f"select as_of, prior_pattern, recent_pattern from ops.format_drift_daily where monitor = 'wms.bin' and entity = '{DRIFT['entity']}' and is_drift order by as_of")
    assert got, "a relabelled bin scheme went unnoticed"
    assert got[0][0] - DRIFT["first_day"] <= timedelta(days=3)
    assert (got[0][1], got[0][2]) == ("A-12-3", "A12-03")


def test_untouched_streams_stay_quiet(mon):
    """The control group: every stream and entity without an injected incident raises nothing, on any night."""
    assert rows(mon, f"select stream, as_of from ops.freshness_daily where is_late and stream <> '{OUTAGE['stream']}'") == []
    assert rows(mon, f"select stream, arrival from ops.volume_daily where is_anomaly and stream <> '{SPIKE['stream']}'") == []
    assert rows(mon, f"select monitor, entity from ops.format_drift_daily where is_drift and not (monitor = 'wms.bin' and entity = '{DRIFT['entity']}')") == []
