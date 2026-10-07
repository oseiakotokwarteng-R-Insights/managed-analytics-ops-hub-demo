"""Command line for the raw-layer loader.
  python -m pipeline.run backfill [--from 2024-10-01] [--to 2026-09-30] [--fresh]   replay history as nightly runs
  python -m pipeline.run once --as-of 2026-10-01                                      one nightly run
  python -m pipeline.run status                                                       recent runs, held files, open alerts"""
from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

from . import config as cfg
from .ingest.engine import Ingestor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["backfill", "once", "status"])
    ap.add_argument("--from", dest="start", default="2024-10-01")
    ap.add_argument("--to", dest="end", default="2026-09-30")
    ap.add_argument("--as-of", dest="as_of")
    ap.add_argument("--db")
    ap.add_argument("--fresh", action="store_true", help="delete the warehouse file first (backfill only)")
    a = ap.parse_args()
    db = a.db or cfg.WAREHOUSE
    if a.cmd == "backfill" and a.fresh and Path(db).exists():
        Path(db).unlink()
    ing = Ingestor(db)
    if a.cmd == "backfill":
        t = time.time()
        res = ing.backfill(date.fromisoformat(a.start), date.fromisoformat(a.end),
                           progress=lambda d, r: print(f"  {d}  loaded {r['loaded']:>3} files  held {r['held']:>2}  [{time.time() - t:5.0f}s]", flush=True))
        print(f"{len(res)} nightly runs, {sum(r['loaded'] for r in res):,} files, {sum(r['rows'] for r in res):,} rows in {time.time() - t:.0f}s")
    elif a.cmd == "once":
        print(ing.run(date.fromisoformat(a.as_of)))
    else:
        c = ing.con
        print(c.execute("SELECT run_id, as_of, status, files_loaded, files_held, files_failed, rows_loaded FROM raw._load_runs ORDER BY run_id DESC LIMIT 5").fetchdf().to_string())
        print(c.execute("SELECT rel_path, status FROM raw._file_registry WHERE status <> 'LOADED'").fetchdf().to_string())
        print(c.execute("SELECT severity, code, as_of, message FROM raw._alerts WHERE resolved_run_id IS NULL").fetchdf().to_string())
    ing.close()


if __name__ == "__main__":
    main()
