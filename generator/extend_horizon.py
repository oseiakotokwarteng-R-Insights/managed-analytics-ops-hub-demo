"""Generate, or extend, the hidden future that the live clock releases one day at a time.
Usage: python -m generator.extend_horizon --to 2027-09-30 [--keep-going]

Runs the simulation and the five source builders out to the new horizon, staging into truth_live_new/ and sources_live_new/. Before anything is swapped in it proves the
extension is safe: every file already delivered to sources/ (arrived on or before the live clock's date, or the end of history) must be identical in the new tree
(spreadsheets are compared by cell content, because the zip container carries timestamps). The one allowed difference is a carrier file from the last two weeks before the
cut that gains records: a shipment still in transit at the cut was never in the old file, so it first appears on its first later day. Only then do truth_live/ and
sources_live/ become the new future. Takes about ten minutes.

Why this works: every day of the simulation draws from its own keyed random stream and every defect decision is a pure function of the record key, with rates normalised on
the frozen history, so adding days never changes a day that already exists."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

from . import config as C

ROOT = C.ROOT
DELIVERED = ROOT / "sources"


def sig(p: Path) -> str:
    if p.suffix == ".xlsx":
        z = zipfile.ZipFile(p)
        return hashlib.sha256(b"".join(z.read(n) for n in sorted(z.namelist()) if n.startswith("xl/worksheets") or n == "xl/sharedStrings.xml")).hexdigest()
    return hashlib.sha256(p.read_bytes()).hexdigest()


def delivered_through() -> "date":
    clock = ROOT / "warehouse" / "live_clock.json"
    return date.fromisoformat(json.loads(clock.read_text())["sim_date"]) if clock.exists() else C.HISTORY_END


def records(p: Path):
    if p.suffix == ".json":
        return {json.dumps(r, sort_keys=True) for r in json.loads(p.read_text())}
    return set(p.read_text(encoding="utf-8").splitlines()[1:])


def check_delivered(new_src: Path):
    """Returns (violations, tolerated): delivered files that differ in the new future, and the in-transit carrier files that only gained records."""
    from pipeline import config as pcfg
    from pipeline.ingest.engine import Ingestor
    probe = Ingestor.__new__(Ingestor)
    probe.sources, probe.tables = DELIVERED, json.loads(pcfg.CONTRACTS.read_text())["tables"]
    through, bad, tol = delivered_through(), [], []
    for it in probe.discover():
        if it.arrival > through:
            continue  # a placeholder for a day that has not arrived: it will be replaced when its day comes
        q = new_src / it.rel
        if q.exists() and sig(it.path) == sig(q):
            continue
        seam = it.rel.startswith("freight/carrier_") and it.arrival >= C.HISTORY_END - timedelta(days=14) and q.exists() and it.path.suffix in (".json", ".csv") and records(it.path) <= records(q)
        (tol if seam else bad).append(it.rel)
    return bad, tol


def make_seam_supplements(new_src: Path, tolerated: list[str]) -> list[str]:
    """Carrier B lists a shipment once, in the file for its ship day. A shipment still in transit at the cut is missing from the file that was delivered, so the rows it
    lacks go out on the first day after the cut as a supplementary file (the carrier catching up on late additions). Carrier A needs nothing: its records reappear with
    every later event."""
    groups: dict = {}
    for rel in tolerated:
        if not rel.endswith(".csv"):
            continue
        old = (DELIVERED / rel).read_text(encoding="utf-8").splitlines()
        new = (new_src / rel).read_text(encoding="utf-8").splitlines()
        have = set(old[1:])
        groups.setdefault((Path(rel).parent, Path(rel).name.split("_")[0], new[0]), []).extend(r for r in new[1:] if r not in have)
    day = C.HISTORY_END + timedelta(days=1)
    out = []
    for (folder, stem, header), rows in groups.items():
        if rows:
            f = new_src / folder / f"{stem}_{day:%Y%m%d}_seam.csv"
            f.write_text(chr(10).join([header, *sorted(set(rows))]) + chr(10), encoding="utf-8")
            out.append(f"{f.relative_to(new_src).as_posix()} ({len(set(rows))} rows)")
    return out


def run(module: str, env: dict):
    t = time.time()
    p = subprocess.run([sys.executable, "-m", module], cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True)
    print(f"  {module}: {time.time() - t:.0f}s")
    if p.returncode:
        raise SystemExit(f"{module} failed:\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--supplements-only", action="store_true", help="only (re)write the seam supplement files into the current sources_live/")
    ap.add_argument("--keep-going", action="store_true", help="swap in the new future even if delivered files differ (never use after launch)")
    a = ap.parse_args()
    if a.supplements_only:
        diffs, tolerated = check_delivered(ROOT / "sources_live")
        print("seam supplements:", make_seam_supplements(ROOT / "sources_live", tolerated))
        return
    truth, src = ROOT / "truth_live_new", ROOT / "sources_live_new"
    for d in (truth, src):
        shutil.rmtree(d, ignore_errors=True)
    env = {"OPS_HUB_HORIZON_END": a.to, "OPS_HUB_TRUTH_DIR": str(truth), "OPS_HUB_SOURCES_OUT": str(src)}
    print(f"generating the future to {a.to}")
    run("generator.run_history", env)
    run("generator.build_sources", env)
    (src / "_horizon.json").write_text(json.dumps({"horizon_end": a.to, "history_end": str(C.HISTORY_END)}))
    diffs, tolerated = check_delivered(src)
    print(f"delivered files checked against the new future: {len(diffs)} differ, {len(tolerated)} carrier files from the last two weeks of history only gained in-transit shipments")
    print("seam supplements:", make_seam_supplements(src, tolerated))
    if diffs and not a.keep_going:
        print("\n".join(diffs[:20]))
        raise SystemExit("the extension would change files that were already delivered; nothing was swapped. Fix the non-causal rule that produced them.")
    for name, new in (("truth_live", truth), ("sources_live", src)):
        old = ROOT / name
        shutil.rmtree(old, ignore_errors=True)
        new.rename(old)
    print(f"future ready: {ROOT / 'sources_live'}")


if __name__ == "__main__":
    main()
