"""The live clock: one simulated day per real day, run exactly as a nightly scheduler would.

  python -m pipeline.live init [--launch-date 2026-10-07]   start the clock at the end of history (delivered files stay as they are)
  python -m pipeline.live status                            where the clock stands, what the next tick will do, recent runs
  python -m pipeline.live tick [--catch-up | --days N | --to YYYY-MM-DD]
                                                            release the files that arrive on each simulated day, load them, rebuild the models,
                                                            refresh the alert log and health view, and re-export the dashboard data
  python -m pipeline.live render                            re-export the dashboard data without advancing the clock

Design: the future was generated in advance by the same deterministic generator (sources_live/, hidden from the pipeline); a tick only releases a day's worth of
files into the drop folder (sources/), which is exactly what a source system delivering overnight would do. Every step is idempotent and the clock moves only after
every step has succeeded, so a failed night is simply run again; a multi-day catch-up loads each night in order and rebuilds the models once at the end.
Scheduling: run `tick --catch-up` once a day from any scheduler (cron, Windows Task Scheduler, a GitHub Actions cron); see docs/RUNBOOK.md."""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config as cfg
from .ingest.engine import Ingestor

STATE = cfg.WAREHOUSE.parent
CLOCK = STATE / "live_clock.json"
RUNS = STATE / "live_runs.jsonl"
LOCK = STATE / "live.lock"
BACKUP = STATE / "history_backup.duckdb"  # the warehouse as it stood at the end of history, so the demo can be reset
MANIFEST = STATE / "history_files.txt"  # every file delivered by the end of history
PLACEHOLDERS = STATE / "history_placeholders"  # the files in the drop folder at the end of history that belong to days not yet arrived; a tick replaces them with the real ones
FUTURE = Path(os.environ.get("OPS_HUB_FUTURE", cfg.ROOT / "sources_live"))
HISTORY_END = date(2026, 9, 30)
SLA_MINUTES = 30  # spec: the daily live run completes and the exports refresh within 30 minutes


def now():
    return datetime.now(timezone.utc)


def read_clock() -> dict | None:
    return json.loads(CLOCK.read_text(encoding="utf-8")) if CLOCK.exists() else None


def write_clock(c: dict):
    tmp = CLOCK.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=2), encoding="utf-8")
    os.replace(tmp, CLOCK)


def horizon_end() -> date:
    """Last day the generated future covers (recorded by the generator next to the future sources)."""
    f = FUTURE / "_horizon.json"
    return date.fromisoformat(json.loads(f.read_text())["horizon_end"]) if f.exists() else HISTORY_END


def target_for_today(c: dict) -> date:
    return date.fromisoformat(c["history_end"]) + timedelta(days=(now().date() - date.fromisoformat(c["launch_real_date"])).days)


class Lock:
    """One tick at a time: the warehouse is a single-writer DuckDB file."""

    def __enter__(self):
        if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 3 * 3600:
            raise SystemExit(f"another tick is running (lock {LOCK}); if it crashed, delete the file")
        LOCK.write_text(f"{os.getpid()} {now().isoformat()}")
        return self

    def __exit__(self, *a):
        LOCK.unlink(missing_ok=True)


def release(ing: Ingestor, through: date) -> dict:
    """Deliver every pre-generated file that has arrived by `through` and is not yet in the drop folder."""
    probe = Ingestor.__new__(Ingestor)  # discovery only: reuse the contract rules for 'arrival', without opening the warehouse
    probe.sources, probe.tables = FUTURE, ing.tables
    n = size = 0
    for it in probe.discover():
        if it.arrival > through:
            break
        dst = cfg.SOURCES / it.rel
        # a file that is already in the drop folder stays, unless it is a placeholder for a day that has not arrived yet and the real file differs
        if dst.exists() and (it.arrival <= HISTORY_END or filecmp.cmp(dst, it.path, shallow=False)):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(it.path, dst)
        n += 1
        size += it.size
    return {"files": n, "bytes": size}


def log_run(rec: dict):
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def recent_runs(n=15) -> list[dict]:
    if not RUNS.exists():
        return []
    return [json.loads(x) for x in RUNS.read_text(encoding="utf-8").splitlines()[-n:]]


def tick(to: date, build_tests: bool = True) -> dict:
    c = read_clock()
    if not c:
        raise SystemExit("clock not initialised: run `python -m pipeline.live init`")
    cur = date.fromisoformat(c["sim_date"])
    if to > horizon_end():
        raise SystemExit(f"{to} is beyond the generated future ({horizon_end()}). Extend it: python -m generator.extend_horizon --to <date>")
    if to <= cur:
        print(f"already at {cur}; nothing to do")
        return {"status": "NOOP", "sim_date": str(cur)}
    from . import build
    from .export import dashboard
    rec = {"started": now().isoformat(timespec="seconds"), "from": str(cur), "to": str(to), "days": (to - cur).days, "steps": {}}
    t0 = time.perf_counter()
    try:
        with Lock():
            ing = Ingestor(cfg.WAREHOUSE)
            d = cur
            rel = {"files": 0, "bytes": 0}
            loaded = held = rows = 0
            ts = time.perf_counter()
            while d < to:
                d += timedelta(days=1)
                r = release(ing, d)
                rel["files"] += r["files"]
                rel["bytes"] += r["bytes"]
                out = ing.run(d)
                loaded += out["loaded"]
                held += out["held"]
                rows += out["rows"]
            ing.close()
            rec["steps"]["release_and_load"] = {"seconds": round(time.perf_counter() - ts, 1), "files_released": rel["files"], "mb": round(rel["bytes"] / 1e6, 1), "files_loaded": loaded, "files_held": held, "rows": rows}
            ts = time.perf_counter()
            build.main(as_of=str(to), test=build_tests)
            rec["steps"]["models_tests_alerts"] = {"seconds": round(time.perf_counter() - ts, 1)}
            ts = time.perf_counter()
            dashboard.main()
            rec["steps"]["export"] = {"seconds": round(time.perf_counter() - ts, 1)}
            c.update({"sim_date": str(to), "last_tick_utc": now().isoformat(timespec="seconds")})
            write_clock(c)
        rec["status"] = "OK"
    except SystemExit as e:
        rec["status"] = "SKIPPED" if "another tick is running" in str(e) else "FAILED"  # a refused second tick did nothing, so it is not a run
        rec["error"] = str(e)
        raise
    except Exception as e:  # noqa: BLE001
        rec["status"] = "FAILED"
        rec["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        rec["seconds"] = round(time.perf_counter() - t0, 1)
        rec["within_sla"] = rec["seconds"] <= SLA_MINUTES * 60
        if rec["status"] != "SKIPPED":
            log_run(rec)
        if rec["status"] == "OK":
            dashboard.write_live(read_clock(), recent_runs())
    print(f"tick {rec['from']} -> {rec['to']}: {rec['status']} in {rec['seconds']:.0f}s ({'within' if rec['within_sla'] else 'OVER'} the {SLA_MINUTES}-minute budget)")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "status", "tick", "render", "reset"])
    ap.add_argument("--launch-date")
    ap.add_argument("--catch-up", action="store_true")
    ap.add_argument("--days", type=int)
    ap.add_argument("--to")
    ap.add_argument("--no-test", action="store_true")
    a = ap.parse_args()
    if a.cmd == "init":
        if read_clock():
            raise SystemExit(f"clock already initialised: {read_clock()}")
        MANIFEST.write_text(chr(10).join(sorted(p.relative_to(cfg.SOURCES).as_posix() for p in cfg.SOURCES.rglob("*") if p.is_file())), encoding="utf-8")
        shutil.copy2(cfg.WAREHOUSE, BACKUP)
        probe = Ingestor.__new__(Ingestor)
        probe.sources, probe.tables = cfg.SOURCES, json.loads(cfg.CONTRACTS.read_text())["tables"]
        shutil.rmtree(PLACEHOLDERS, ignore_errors=True)
        for it in probe.discover():
            if it.arrival > HISTORY_END:
                (PLACEHOLDERS / it.rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(it.path, PLACEHOLDERS / it.rel)
        write_clock({"history_end": str(HISTORY_END), "sim_date": str(HISTORY_END), "launch_real_date": a.launch_date or str(now().date()), "created_utc": now().isoformat(timespec="seconds")})
        print(f"clock initialised at {HISTORY_END}; backed up the warehouse and listed {len(MANIFEST.read_text().splitlines()):,} delivered files so `reset` can undo live ticks")
    elif a.cmd == "reset":
        if not (BACKUP.exists() and MANIFEST.exists()):
            raise SystemExit("nothing to reset to: run `init` first")
        keep = set(MANIFEST.read_text(encoding="utf-8").splitlines())
        gone = 0
        for p in list(cfg.SOURCES.rglob("*")):
            if p.is_file() and p.relative_to(cfg.SOURCES).as_posix() not in keep:
                p.unlink()
                gone += 1
        for p in PLACEHOLDERS.rglob("*") if PLACEHOLDERS.exists() else []:
            if p.is_file():
                shutil.copy2(p, cfg.SOURCES / p.relative_to(PLACEHOLDERS))
        shutil.copy2(BACKUP, cfg.WAREHOUSE)
        for f in (CLOCK, RUNS, LOCK, cfg.ROOT / "dashboard" / "data" / "live.json"):
            f.unlink(missing_ok=True)
        print(f"reset to the end of history: removed {gone:,} released files, restored the placeholder files, restored the warehouse, cleared the clock (run `init` again to restart it)")
    elif a.cmd == "status":
        c = read_clock()
        print(json.dumps(c, indent=2) if c else "clock not initialised")
        if c:
            print(f"today's target: {target_for_today(c)}  (behind by {(target_for_today(c) - date.fromisoformat(c['sim_date'])).days} days); generated future ends {horizon_end()}")
            for r in recent_runs(5):
                print(f"  {r['started']}  {r['from']} -> {r['to']}  {r['status']}  {r['seconds']:.0f}s")
    elif a.cmd == "render":
        from .export import dashboard
        dashboard.main()
        dashboard.write_live(read_clock(), recent_runs())
    else:
        c = read_clock()
        if not c:
            raise SystemExit("clock not initialised")
        cur = date.fromisoformat(c["sim_date"])
        to = date.fromisoformat(a.to) if a.to else (cur + timedelta(days=a.days) if a.days else (target_for_today(c) if a.catch_up else cur + timedelta(days=1)))
        tick(to, build_tests=not a.no_test)


if __name__ == "__main__":
    main()
