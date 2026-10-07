"""Ingestion guarantees, tested on a small sandbox of real source files.  Run: python -m pytest tests -q"""
from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from pipeline import config as cfg
from pipeline.ingest.checks import content_hash, raw_tables
from pipeline.ingest.engine import Ingestor

from .sandbox import build

END = date(2026, 6, 10)
START = date(2024, 10, 1)


@pytest.fixture(scope="session")
def master(tmp_path_factory):
    return build(tmp_path_factory.mktemp("sandbox_master") / "src")


@pytest.fixture()
def sb(master, tmp_path):
    dst = tmp_path / "src"
    shutil.copytree(master, dst)
    return dst


def ing(sb, tmp_path, contracts=None):
    return Ingestor(tmp_path / "t.duckdb", sb, contracts)


def snapshot(i):
    return {t: content_hash(i.con, t) for t in raw_tables(i.con)}


def test_rerun_is_a_noop(sb, tmp_path):
    i = ing(sb, tmp_path)
    i.backfill(START, END)
    before = snapshot(i)
    files = i.con.execute("SELECT COUNT(*) FROM raw._load_files").fetchone()[0]
    out = i.run(END)
    assert out["loaded"] == 0 and out["rows"] == 0 and out["failed"] == 0
    assert snapshot(i) == before
    assert i.con.execute("SELECT COUNT(*) FROM raw._load_files").fetchone()[0] == files
    i.close()
    j = ing(sb, tmp_path)  # a fresh process picks the registry up from the database
    assert j.run(END)["loaded"] == 0
    assert snapshot(j) == before


def test_raw_is_as_received(sb, tmp_path):
    i = ing(sb, tmp_path)
    i.run(date(2025, 3, 12))
    p = sb / "erp/sales_order_line/so_line_20250312.csv"
    with open(p, newline="", encoding="utf-8") as f:
        rd = csv.reader(f)
        hdr = next(rd)
        src = [tuple(None if v == "" else v for v in r) for r in rd]
    fid = i.con.execute("SELECT file_id FROM raw._load_files WHERE rel_path = ?", [p.relative_to(sb).as_posix()]).fetchone()[0]
    got = i.con.execute(f"SELECT {', '.join(hdr)} FROM raw.erp_sales_order_line WHERE _file_id = ? ORDER BY _row_num", [fid]).fetchall()
    assert got == src  # every value identical, text kept as text ("9" stays "9"), blanks as NULL
    legacy = i.con.execute("SELECT item_code FROM raw.legacy_inv_trans").fetchall()
    assert any(r[0] != r[0].strip() for r in legacy), "legacy padding must survive raw"


def test_changed_file_is_a_new_version_and_old_rows_stay(sb, tmp_path):
    i = ing(sb, tmp_path)
    i.run(date(2025, 3, 12))
    p = sb / "erp/po_header/po_header_20250311.csv"
    n0 = i.con.execute("SELECT COUNT(*) FROM raw.erp_po_header").fetchone()[0]
    rows = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join(rows + [rows[1]]) + "\n", encoding="utf-8")  # the source re-sends a corrected file under the same name
    out = i.run(date(2025, 3, 12))
    assert out["loaded"] == 1
    n1 = i.con.execute("SELECT COUNT(*) FROM raw.erp_po_header").fetchone()[0]
    assert n1 == n0 + (len(rows) - 1) + 1  # v1 rows retained, all v2 rows added
    v = i.con.execute("SELECT version, status FROM raw._load_files WHERE rel_path LIKE '%po_header_20250311%' ORDER BY version").fetchall()
    assert v == [(1, "LOADED"), (2, "RELOADED_CHANGED")]
    assert i.run(date(2025, 3, 12))["loaded"] == 0


def test_crash_mid_file_is_atomic_and_recovers(sb, tmp_path):
    i = ing(sb, tmp_path)
    target = "erp/sales_order_line/so_line_20250311.csv"

    def boom(rel, stage):
        if rel == target:
            raise RuntimeError("simulated crash after insert, before commit")
    out = i.run(date(2025, 3, 12), fail_hook=boom)
    assert out["failed"] == 1 and out["status"] == "PARTIAL"
    assert i.con.execute("SELECT COUNT(*) FROM raw._file_registry WHERE rel_path = ? AND status = 'FAILED'", [target]).fetchone()[0] == 1
    fids = [r[0] for r in i.con.execute("SELECT file_id FROM raw._load_files WHERE rel_path = ?", [target]).fetchall()]
    assert i.con.execute("SELECT COUNT(*) FROM raw.erp_sales_order_line WHERE _file_id IN (SELECT UNNEST(?))", [fids]).fetchone()[0] == 0, "partial rows leaked"
    assert i.con.execute("SELECT COUNT(*) FROM raw._alerts WHERE code = 'LOAD_FAILED'").fetchone()[0] == 1
    assert i.con.execute("SELECT COUNT(*) FROM raw.erp_sales_order_line").fetchone()[0] > 0, "other files must still load"
    out2 = i.run(date(2025, 3, 12))
    assert out2["loaded"] == 1 and out2["failed"] == 0
    with open(sb / target, newline="", encoding="utf-8") as f:
        want = sum(1 for _ in f) - 1
    got = i.con.execute("SELECT COUNT(*) FROM raw.erp_sales_order_line WHERE _file_id = (SELECT file_id FROM raw._load_files WHERE rel_path = ? AND status = 'LOADED')", [target]).fetchone()[0]
    assert got == want


def test_corrupt_file_fails_alone_then_loads_when_fixed(sb, tmp_path):
    i = ing(sb, tmp_path)
    p = sb / "freight/carrier_a/shipments_20250311.json"
    good = p.read_text(encoding="utf-8")
    p.write_text(good[: len(good) // 2], encoding="utf-8")  # truncated transfer
    out = i.run(date(2025, 3, 12))
    assert out["failed"] == 1 and out["loaded"] > 10
    p.write_text(good, encoding="utf-8")
    out2 = i.run(date(2025, 3, 12))
    assert out2["loaded"] == 1 and out2["failed"] == 0
    assert i.con.execute("SELECT COUNT(*) FROM raw.carrier_a_shipments").fetchone()[0] > 0


def test_breaking_drift_is_held_then_released_on_approval(sb, tmp_path):
    i = ing(sb, tmp_path)
    items = i.discover()
    pre = i.backfill(START, date(2026, 6, 3))
    held_before = i.con.execute("SELECT COUNT(*) FROM raw._file_registry WHERE status = 'HELD_DRIFT'").fetchone()[0]
    assert held_before == 0
    for d in (date(2026, 6, 4), date(2026, 6, 5), date(2026, 6, 6)):
        out = i.run(d, items)
        assert out["status"] == "OK_WITH_HELD_FILES"
    held = i.con.execute("SELECT rel_path FROM raw._file_registry WHERE status = 'HELD_DRIFT' ORDER BY 1").fetchall()
    assert [h[0][-12:] for h in held] == ["20260604.csv", "20260605.csv", "20260606.csv"]
    nrows = i.con.execute("SELECT COUNT(*) FROM raw.carrier_b_shipments").fetchone()[0]
    cols = {r[1] for r in i.con.execute("PRAGMA table_info('raw.carrier_b_shipments')").fetchall()}
    assert "wt_lbs" not in cols, "held files must not change the raw schema or load rows"
    alerts = i.con.execute("SELECT code, severity FROM raw._alerts WHERE resolved_run_id IS NULL").fetchall()
    assert alerts.count(("SCHEMA_DRIFT_HELD", "ERROR")) == 3
    out = i.run(date(2026, 6, 8), items)  # contract v2 is approved on 2026-06-08
    assert out["released"] == 3 and out["status"] == "OK"
    assert i.con.execute("SELECT COUNT(*) FROM raw.carrier_b_shipments WHERE wt_lbs IS NOT NULL").fetchone()[0] > 0
    assert i.con.execute("SELECT COUNT(*) FROM raw.carrier_b_shipments WHERE weight_lb IS NOT NULL AND wt_lbs IS NOT NULL").fetchone()[0] == 0
    assert i.con.execute("SELECT COUNT(*) FROM raw._alerts WHERE resolved_run_id IS NULL AND severity = 'ERROR'").fetchone()[0] == 0
    assert i.con.execute("SELECT COUNT(*) FROM raw.carrier_b_shipments").fetchone()[0] > nrows


def test_unapproved_contract_never_loads(sb, tmp_path):
    c = json.loads(cfg.CONTRACTS.read_text())
    c["tables"]["carrier_b_shipments"]["versions"][1]["approved_on"] = "2099-01-01"  # nobody approves v2
    i = ing(sb, tmp_path, c)
    out = i.backfill(START, END)
    assert out[-1]["status"] == "OK_WITH_HELD_FILES"
    assert i.con.execute("SELECT COUNT(*) FROM raw._file_registry WHERE status = 'HELD_DRIFT'").fetchone()[0] >= 4
    new_files = ("0604", "0605", "0606", "0608", "0609", "0610")
    q = "SELECT COUNT(*) FROM raw._load_files WHERE table_name = 'carrier_b_shipments' AND status IN ('LOADED','RELOADED_CHANGED') AND (" + " OR ".join(f"rel_path LIKE '%2026{d}%'" for d in new_files) + ")"
    assert i.con.execute(q).fetchone()[0] == 0, "no new-schema file may load without an approved contract"
    assert i.con.execute("SELECT COUNT(*) FROM raw._file_registry WHERE table_name = 'carrier_b_shipments' AND status = 'LOADED'").fetchone()[0] == 5  # the five old-schema days still load


def test_additive_drift_loads_with_alert(sb, tmp_path):
    p = sb / "freight/carrier_b/tracking_20250311.csv"
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    rows[0].append("scan_device")
    for r in rows[1:]:
        r.append("HX-9")
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    i = ing(sb, tmp_path)
    i.run(date(2025, 3, 12))
    cols = {r[1] for r in i.con.execute("PRAGMA table_info('raw.carrier_b_tracking')").fetchall()}
    assert "scan_device" in cols
    assert i.con.execute("SELECT COUNT(*) FROM raw.carrier_b_tracking WHERE scan_device = 'HX-9'").fetchone()[0] == len(rows) - 1
    assert i.con.execute("SELECT kind FROM raw._schema_drift WHERE rel_path LIKE '%tracking_20250311%'").fetchone()[0] == "ADDITIVE"
    assert i.con.execute("SELECT severity FROM raw._alerts WHERE code = 'SCHEMA_ADDITIVE'").fetchone()[0] == "INFO"
    assert i.con.execute("SELECT COUNT(*) FROM raw._file_registry WHERE status = 'HELD_DRIFT'").fetchone()[0] == 0


def test_late_arriving_file_is_picked_up(sb, tmp_path):
    p = sb / "erp/sales_order_line/so_line_20250310.csv"
    hidden = tmp_path / "so_line_20250310.csv"
    shutil.move(p, hidden)  # the 03-10 extract is missing on night one
    i = ing(sb, tmp_path)
    i.run(date(2025, 3, 12))
    assert i.con.execute("SELECT COUNT(*) FROM raw._file_registry WHERE rel_path LIKE '%so_line_20250310%'").fetchone()[0] == 0
    shutil.move(hidden, p)  # it turns up two days late
    out = i.run(date(2025, 3, 14))
    assert out["loaded"] == 1
    row = i.con.execute("SELECT arrival, loaded_ts FROM raw._load_files WHERE rel_path LIKE '%so_line_20250310%'").fetchone()
    assert row[1].date() > row[0], "loaded_ts records the real (late) load time, not the file date"


def test_every_raw_row_has_lineage(sb, tmp_path):
    i = ing(sb, tmp_path)
    i.backfill(START, END)
    for t in raw_tables(i.con):
        orphan = i.con.execute(f"SELECT COUNT(*) FROM raw.{t} r LEFT JOIN raw._load_files f ON f.file_id = r._file_id AND f.status IN ('LOADED','RELOADED_CHANGED') WHERE f.file_id IS NULL").fetchone()[0]
        assert orphan == 0, t
    tot = i.con.execute("SELECT SUM(rows_loaded) FROM raw._load_files WHERE status IN ('LOADED','RELOADED_CHANGED')").fetchone()[0]
    assert tot == sum(i.con.execute(f"SELECT COUNT(*) FROM raw.{t}").fetchone()[0] for t in raw_tables(i.con))


def test_daily_replay_equals_one_shot_backfill(sb, tmp_path):
    a = Ingestor(tmp_path / "a.duckdb", sb)
    a.backfill(START, END)
    b = Ingestor(tmp_path / "b.duckdb", sb)
    b.run(END)
    assert snapshot(a) == snapshot(b)


def test_pipeline_never_touches_the_truth_store():
    bad = []
    for p in (cfg.ROOT / "pipeline").rglob("*.py"):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\btruth\b|from generator|import generator", line, re.I) and "never read" not in line.lower():
                bad.append(f"{p.name}:{n}: {line.strip()}")
    assert not bad, bad
    assert "truth" not in str(cfg.SOURCES).lower()
