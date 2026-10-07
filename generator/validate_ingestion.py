"""Phase 3 gate for the raw layer.  Usage: python -m generator.validate_ingestion [--full]
--full also builds a one-shot backfill into a scratch database and proves the nightly replay produces identical content.

This is a test harness: it may read the generator's answer key (truth/) to cross-check what the pipeline preserved.
The pipeline itself (pipeline/ingest, pipeline/run.py) never does; tests/test_ingest.py enforces that."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

import shutil

from pipeline import config as cfg
from pipeline.ingest.checks import content_hash, raw_tables
from pipeline.ingest.engine import Ingestor

from . import config as G
from .validate import Results

END = date(2026, 9, 30)
START = date(2024, 10, 1)


def independent_rows(ing: Ingestor, items) -> dict:
    """Row counts read straight from the files by separate code paths (csv module, line counts, json, openpyxl)."""
    out: dict = {}
    for it in items:
        if it.arrival > END:
            continue
        kind = ing.tables[it.table]["kind"]
        rt = ing.raw_table(it.table)
        if kind == "csv":
            with open(it.path, newline="", encoding="utf-8") as f:
                n = sum(1 for _ in csv.reader(f)) - 1
        elif kind == "jsonl":
            with open(it.path, encoding="utf-8") as f:
                n = sum(1 for line in f if line.strip())
        elif kind == "json_array":
            n = len(json.loads(it.path.read_text(encoding="utf-8")))
        else:
            from openpyxl import load_workbook
            ws = load_workbook(it.path, read_only=True).active
            n = sum(1 for r in ws.iter_rows(max_col=10, values_only=True) if any(v is not None for v in r))
        out[rt] = out.get(rt, 0) + n
    return out


def q1(con, sql, *a):
    return con.execute(sql, list(a)).fetchone()[0]


def main():
    full = "--full" in sys.argv
    R = Results()
    scratch = cfg.ROOT / "warehouse" / "idem_check.duckdb"
    shutil.copy2(cfg.WAREHOUSE, scratch)  # the idempotency probe runs on a copy so the audited history is never touched
    ing = Ingestor(scratch)
    con = duckdb.connect(str(cfg.WAREHOUSE), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    items = ing.discover()
    elig = [i for i in items if i.arrival <= END]
    late = [i for i in items if i.arrival > END]

    print("A. Completeness")
    reg = con.execute("SELECT rel_path, status, sha256, size_bytes FROM raw._file_registry").fetchdf().set_index("rel_path")
    missing = [i.rel for i in elig if i.rel not in reg.index or reg.status[i.rel] != "LOADED"]
    R.add("A", "every file that had arrived by 2026-09-30 is loaded", f"{len(elig) - len(missing):,} of {len(elig):,} files; {len(late)} not yet arrived (live window)", "all", not missing)
    want = independent_rows(ing, items)
    have = {t: q1(con, f"SELECT COUNT(*) FROM raw.{t}") for t in raw_tables(con)}
    bad = {t: (have.get(t), want.get(t)) for t in set(want) | set(have) if have.get(t) != want.get(t)}
    R.add("A", "raw row counts equal an independent recount of the source files (every table)", f"{sum(have.values()):,} rows over {len(have)} tables; {len(bad)} tables differ {bad if bad else ''}", "0 differ", not bad)
    tot = q1(con, "SELECT SUM(rows_loaded) FROM raw._load_files WHERE status IN ('LOADED','RELOADED_CHANGED')")
    R.add("A", "audit trail adds up: sum of per-file rows_loaded = rows in raw", f"{tot:,} vs {sum(have.values()):,}", "equal", tot == sum(have.values()))
    st = con.execute("SELECT status, COUNT(*) n FROM raw._file_registry GROUP BY 1").fetchdf().set_index("status").n.to_dict()
    R.add("A", "nothing left held or failed at the end of history", f"{st}", "only LOADED", set(st) == {"LOADED"})

    print("B. Idempotency and integrity")
    before = {t: content_hash(ing.con, t) for t in raw_tables(ing.con)}
    n_attempts = q1(ing.con, "SELECT COUNT(*) FROM raw._load_files")
    out = ing.run(END, items)
    after = {t: content_hash(ing.con, t) for t in raw_tables(ing.con)}
    no_new = q1(ing.con, "SELECT COUNT(*) FROM raw._load_files") == n_attempts
    R.add("B", "re-running the whole history changes nothing", f"loaded {out['loaded']} files, {out['rows']} rows; content hashes {'identical' if before == after else 'DIFFER'}; no new audit rows: {no_new}",
          "0 / 0 / identical", out["loaded"] == 0 and out["rows"] == 0 and before == after and no_new)
    t = time.time()
    drift = [i.rel for i in elig if hashlib.sha256(i.path.read_bytes()).hexdigest() != reg.sha256[i.rel]]
    R.add("B", "registry matches the disk: re-hashing every loaded file reproduces its recorded sha256", f"{len(elig) - len(drift):,} of {len(elig):,} match ({time.time() - t:.0f}s)", "all", not drift)
    orphan = sum(q1(con, f"SELECT COUNT(*) FROM raw.{t} r LEFT JOIN raw._load_files f ON f.file_id = r._file_id AND f.status IN ('LOADED','RELOADED_CHANGED') WHERE f.file_id IS NULL") for t in raw_tables(con))
    R.add("B", "every raw row traces to a loaded file (lineage)", f"{orphan} orphan rows", "0", orphan == 0)
    tt = q1(con, "SELECT MIN(DATE_DIFF('day', arrival, CAST(loaded_ts AS DATE))) FROM raw._load_files WHERE status = 'LOADED'")
    R.add("B", "no time travel: every file is loaded after it arrived", f"minimum arrival-to-load gap {tt} day(s)", ">= 1", tt >= 1)
    fails = q1(con, "SELECT COUNT(*) FROM raw._load_files WHERE status = 'FAILED'")
    R.add("B", "no load failures across 730 nightly runs", f"{fails}", "0", fails == 0)

    print("C. Schema drift (scenario S2)")
    dr = con.execute("SELECT * FROM raw._schema_drift ORDER BY drift_id").fetchdf()
    held = dr[dr.action == "FILE_HELD"]
    cb = [i for i in elig if i.table == "carrier_b_shipments" and date(2026, 6, 4) <= i.arrival < date(2026, 6, 8)]
    R.add("C", "the Carrier B schema change was detected on the day each file arrived", f"{len(held)} files held; detected on {sorted({str(pd.Timestamp(d).date()) for d in held.detected_as_of})}; expected {len(cb)} files dated 06-04..06-07",
          "all new-schema files before approval", len(held) == len(cb) and all(pd.Timestamp(a).date() == p.arrival for a, p in zip(held.detected_as_of, sorted(cb, key=lambda x: x.arrival))))
    R.add("C", "held files released when the new contract was approved, none lost", f"{int(held.resolved_run_id.notna().sum())}/{len(held)} resolved on {sorted({str(pd.Timestamp(d).date()) for d in held.resolved_as_of})}", "all resolved 2026-06-08",
          held.resolved_run_id.notna().all() and {str(pd.Timestamp(d).date()) for d in held.resolved_as_of} == {"2026-06-08"})
    ev = dr[dr.kind == "EVOLUTION"]
    R.add("C", "raw table evolved exactly once, by approved contract, and nothing else drifted", f"{len(ev)} evolution ({', '.join(ev.added)}); kinds {dr.kind.value_counts().to_dict()}", "1 evolution, 0 other", len(ev) == 1 and set(dr.kind) <= {"BREAKING", "EVOLUTION"})
    openal = q1(con, "SELECT COUNT(*) FROM raw._alerts WHERE resolved_run_id IS NULL")
    R.add("C", "no open alerts at the end", f"{openal} open of {q1(con, 'SELECT COUNT(*) FROM raw._alerts')} raised", "0 open", openal == 0)
    split = con.execute("SELECT SUM((weight_lb IS NOT NULL AND wt_lbs IS NULL)::INT) v1, SUM((weight_lb IS NULL AND wt_lbs IS NOT NULL)::INT) v2, SUM((weight_lb IS NOT NULL AND wt_lbs IS NOT NULL)::INT) both_ FROM raw.carrier_b_shipments").fetchone()
    R.add("C", "no row mixes the two schemas: old rows fill weight_lb, new rows fill wt_lbs", f"v1 rows {split[0]:,}, v2 rows {split[1]:,}, mixed {split[2]}", "mixed = 0", split[2] == 0 and split[0] > 0 and split[1] > 0)
    first_v2 = q1(con, "SELECT MIN(CAST(loaded_ts AS DATE)) FROM raw._load_files WHERE table_name='carrier_b_shipments' AND contract_version = 'v2'")
    R.add("C", "no new-schema file loaded before the contract was approved", f"first v2 load {first_v2}", ">= 2026-06-09 (run after 06-08 approval)", first_v2 >= date(2026, 6, 9))

    print("D. Raw keeps the data as received (cross-checked against the answer key)")
    d = pd.read_parquet(G.TRUTH_DIR / "truth_defects.parquet")
    dups = q1(con, "SELECT COUNT(*) - COUNT(DISTINCT event_id) FROM raw.wms_events")
    w1 = int((d.defect_code == "W1").sum())
    R.add("D", "WMS duplicate deliveries are preserved (dedupe is staging's job)", f"{dups:,} duplicate copies in raw vs {w1:,} injected ({w1 - dups} copies were still in flight at the end of history)", "raw = injected minus in-flight (<= 0.2%)", 0 <= w1 - dups <= 0.002 * w1)
    l5 = int((d.defect_code == "L5").sum())
    badq = q1(con, "SELECT COUNT(*) FROM raw.legacy_inv_trans WHERE TRY_CAST(REPLACE(TRIM(qty), ',', '') AS INTEGER) IS NULL")
    R.add("D", "unparseable legacy quantities are preserved as text", f"{badq} non-numeric qty values in raw vs {l5} injected", "equal", badq == l5)
    late_logged = set(d[d.defect_code.isin(["W2", "S3"])].source_row_key)
    lag = q1(con, """SELECT COUNT(*) FROM (SELECT event_id, MIN(date_diff('minute', CAST(event_ts AS TIMESTAMP), CAST(published_at AS TIMESTAMP))) m
                     FROM raw.wms_events GROUP BY 1) WHERE m >= 360""")
    in_flight = json.loads((G.TRUTH_DIR / "sources_manifest.json").read_text())["stats"]["wms"]["in_flight_excluded"]
    R.add("D", "late-arriving WMS events are loaded with their original timestamps", f"{lag:,} distinct events first delivered >= 6h after they happened vs {len(late_logged):,} logged (W2 union S3); {len(late_logged) - lag} of the logged ones were still in flight at the end of history (all {in_flight} undelivered events)",
          "raw = logged minus in-flight", 0 <= len(late_logged) - lag <= in_flight)
    pad = q1(con, "SELECT COUNT(*) FROM raw.legacy_inv_trans WHERE item_code <> TRIM(item_code)")
    R.add("D", "whitespace and formatting quirks survive raw untouched", f"{pad:,} legacy item codes carry padding", "> 0", pad > 0)
    patterns = q1(con, "SELECT COUNT(DISTINCT cell_types) FROM raw.sheet_cells")
    formulas = q1(con, "SELECT COUNT(*) FROM raw.sheet_cells WHERE cell_types LIKE '%f%'")
    typed_dates = q1(con, "SELECT COUNT(*) FROM raw.sheet_cells WHERE cell_types LIKE '%d%'")
    R.add("D", "spreadsheet cells keep their types (text vs number vs date vs formula)", f"{patterns} cell-type patterns; {formulas:,} formula rows, {typed_dates:,} rows with true date cells", "formulas and dates visible", formulas > 0 and typed_dates > 0)

    print("E. Operations")
    runs = con.execute("SELECT COUNT(*) n, MAX(duration_s) mx, SUM(duration_s) tot FROM raw._load_runs").fetchone()
    R.add("E", "nightly runs recorded for the whole history", f"{runs[0]} runs; slowest {runs[1]:.1f}s; total {runs[2]:.0f}s; database {cfg.WAREHOUSE.stat().st_size / 1e6:.0f} MB", "730 runs", runs[0] == 730)
    py = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], cwd=cfg.ROOT, capture_output=True, text=True)
    last = py.stdout.strip().splitlines()[-1] if py.stdout.strip() else py.stderr[-200:]
    R.add("E", "ingestion test suite (crash safety, changed files, drift, late files, corrupt files, truth guard)", last, "all pass", py.returncode == 0)

    if full:
        print("F. Backfill equivalence")
        oneshot = cfg.ROOT / "warehouse" / "oneshot.duckdb"
        if oneshot.exists():
            oneshot.unlink()
        t = time.time()
        one = Ingestor(oneshot)
        o = one.run(END)
        same = {t_: content_hash(one.con, t_) for t_ in raw_tables(one.con)}
        diff = [t_ for t_ in before if before[t_] != same.get(t_)]
        R.add("F", "one-shot backfill and 730 nightly runs produce identical raw content (every table)", f"{len(before) - len(diff)}/{len(before)} tables identical; one-shot {time.time() - t:.0f}s, status {o['status']}", "all identical", not diff)
        one.close()
        oneshot.unlink()

    write_report(R, con, dr, full)
    chart(con)
    ing.close()
    scratch.unlink()
    print(f"\n{sum(r[4] for r in R.rows)}/{len(R.rows)} checks passed")
    sys.exit(0 if R.all_ok else 1)


def write_report(R, con, dr, full):
    rows = "\n".join(f"| {n} | {m} | {c} | {'PASS' if ok else 'FAIL'} |" for g, n, m, c, ok in R.rows)
    tabs = con.execute("""SELECT f.table_name, COUNT(*) files, SUM(f.rows_loaded) n_rows, MIN(f.arrival) first_arrival, MAX(f.arrival) last_arrival FROM raw._load_files f
                          WHERE f.status IN ('LOADED','RELOADED_CHANGED') GROUP BY 1 ORDER BY 1""").fetchdf()
    inv = "\n".join(f"| {r.table_name} | {r.files:,} | {int(r.n_rows):,} | {r.first_arrival} to {r.last_arrival} |" for r in tabs.itertuples())
    inc = dr[dr.action == "FILE_HELD"]
    tl = "\n".join(f"| {r.detected_as_of} | {r.rel_path.split('/')[-1]} | missing {r.missing}; new {r.added} | held, alert raised | {r.resolved_as_of} ({r.resolution}) |" for r in inc.itertuples())
    runs = con.execute("SELECT status, COUNT(*) n FROM raw._load_runs GROUP BY 1").fetchdf()
    rs = ", ".join(f"{r.status}: {r.n}" for r in runs.itertuples())
    txt = ["# System 1 — Phase 3 Report: Raw-Layer Ingestion\n",
           f"Result: **{'ALL CHECKS PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in R.rows)}/{len(R.rows)}). Backfill-equivalence test {'was' if full else 'was NOT'} run in this pass.\n",
           f"Nightly runs: {rs}.\n", "## What is loaded\n", "| Raw table (by contract) | Files | Rows | Arrival window |\n|---|---|---|---|", inv,
           "\n## Incident replay: Carrier B schema change (S2)\n", "| Detected | File | Change | Action | Released |\n|---|---|---|---|---|", tl,
           "\n## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (cfg.ROOT / "docs" / "PHASE3_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def chart(con):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    r = con.execute("SELECT as_of, rows_loaded, files_loaded, files_held, status FROM raw._load_runs ORDER BY run_id").fetchdf()
    r["as_of"] = pd.to_datetime(r.as_of)
    lag = con.execute("""SELECT FLOOR(date_diff('minute', CAST(event_ts AS TIMESTAMP), CAST(published_at AS TIMESTAMP)) / 60.0) h, COUNT(*) n FROM raw.wms_events GROUP BY 1 ORDER BY 1""").fetchdf()
    fig, ax = plt.subplots(2, 1, figsize=(11, 8))
    ax[0].plot(r.as_of, r.rows_loaded, lw=0.8)
    held = r[r.status == "OK_WITH_HELD_FILES"]
    if len(held):
        ax[0].axvspan(held.as_of.min(), held.as_of.max(), alpha=0.25, color="red", label="Carrier B schema change: files held (06-04 to 06-07)")
        ax[0].legend()
    ax[0].set_title("Rows loaded per nightly run (730 runs replayed from history)")
    ax[0].grid(alpha=0.3)
    ax[1].bar(lag.h.clip(upper=100), lag.n, width=0.9)
    ax[1].set_yscale("log")
    ax[1].set_title("WMS publication lag in hours (log scale): the late-arrival tail and the Flagstaff outage burst are preserved in raw")
    ax[1].set_xlabel("hours between event time and publication (100 = 100 or more)")
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(cfg.ROOT / "docs" / "phase3_ingestion.png", dpi=110)


if __name__ == "__main__":
    main()
