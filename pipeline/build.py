"""Builds the analytical layers after a nightly load: seeds, models, tests, then records the results and refreshes the alert log and health view.
Usage: python -m pipeline.build [--no-test] [--as-of YYYY-MM-DD]   (--as-of moves the dbt history_end variable: the live clock passes the simulated date)"""
from __future__ import annotations

import subprocess
import sys
import time

from . import config as cfg
from .ops.record_dbt import record

DBT = cfg.ROOT / ".venv" / "Scripts" / "dbt.exe"
DBT_DIR = cfg.ROOT / "pipeline" / "dbt"


AS_OF = None


def default_as_of() -> str:
    import re
    return re.search(r'history_end:\s*"([0-9-]+)"', (DBT_DIR / "dbt_project.yml").read_text(encoding="utf-8")).group(1)


def dbt(*args) -> subprocess.CompletedProcess:
    extra = ["--vars", f"{{history_end: '{AS_OF}'}}"] if AS_OF and args[0] in ("run", "test", "seed") else []
    return subprocess.run([str(DBT), *args, *extra, "--profiles-dir", "."], cwd=DBT_DIR, capture_output=True, text=True)


def main(as_of=None, test=None):
    global AS_OF
    AS_OF = as_of or (sys.argv[sys.argv.index("--as-of") + 1] if "--as-of" in sys.argv else None)
    test = ("--no-test" not in sys.argv) if test is None else test
    steps = [("seed", ["seed"]), ("run", ["run"])]
    if test:
        steps.append(("test", ["test"]))
    for name, a in steps:
        t = time.time()
        p = dbt(*a)
        tail = [ln for ln in p.stdout.splitlines() if "Done. PASS" in ln]
        print(f"  dbt {name:5s} {time.time() - t:5.0f}s  {tail[-1].split('Done.')[-1].strip() if tail else p.stdout[-200:]}", flush=True)
        if name == "test":
            print("  recorded:", record(as_of=AS_OF or default_as_of()))
        if p.returncode != 0 and name != "test":
            raise SystemExit(p.returncode)
    t = time.time()
    p = dbt("run", "--select", "alerts_unified", "pipeline_health_daily", "pipeline_health_current")  # picks up the recorded test results
    print(f"  dbt ops refresh {time.time() - t:.0f}s")
    if p.returncode != 0:
        raise SystemExit(1)
    return True


if __name__ == "__main__":
    main()
