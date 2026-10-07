"""Build the five source systems from the truth store.  Usage: python -m generator.build_sources
Order matters: cycle counts compare physical truth with each system's book, so the systems' recorded events come first."""
from __future__ import annotations

import hashlib
import json
import shutil
import time

import pandas as pd

from . import config as C
from .sources import counts, erp, freight, legacy, wms
from .sources.common import SRC, DefectLog, Truth


def main():
    t0 = time.time()
    if SRC.exists():
        shutil.rmtree(SRC)  # generated output only
    SRC.mkdir()
    T, log, stats = Truth(), DefectLog(), {}

    def step(name, fn):
        t = time.time()
        r = fn()
        stats[name] = r
        print(f"  {name:10s} {time.time() - t:5.0f}s", flush=True)
        return r

    step("erp", lambda: erp.build(T, log))
    wms_ev = wms.prepare(T, log)
    leg = legacy.prepare(T, log)
    c, wms_adj, leg_adj = counts.make_counts(T, wms.book_effects(wms_ev), legacy.book_effects(leg), log)
    print(f"  counts prepared: {len(c):,} count events, {int(c.posted.sum()):,} adjustments posted ({time.time() - t0:.0f}s)", flush=True)
    step("wms", lambda: wms.finish(T, pd.concat([wms_ev, wms_adj], ignore_index=True), log))
    keep = ["tkey", "etype", "sku_id", "wh_id", "qty", "ref_no", "mdate", "vendor_id", "unit_cost", "sign", "memo", "src"]
    step("legacy", lambda: legacy.finish(T, pd.concat([leg, leg_adj.assign(src="count_adjust")[keep]], ignore_index=True), log))
    step("counts", lambda: counts.write_counts(T, c, log))
    step("price", lambda: counts.write_price_overrides(T, log))
    step("freight", lambda: freight.build(T, log))

    d = log.frame()
    d.insert(0, "defect_seq", range(1, len(d) + 1))
    d.to_parquet(C.TRUTH_DIR / "truth_defects.parquet", index=False)
    cnt = c.drop(columns=["rank"]).copy()
    cnt.to_parquet(C.TRUTH_DIR / "truth_counts.parquet", index=False)
    wms.bins_table(T).to_parquet(C.TRUTH_DIR / "truth_bins.parquet", index=False)
    files = {p.name: sum(1 for _ in p.rglob("*") if _.is_file()) for p in sorted(SRC.iterdir()) if p.is_dir()}
    size = sum(f.stat().st_size for f in SRC.rglob("*") if f.is_file())
    digests = {}
    for sysdir in sorted(p for p in SRC.iterdir() if p.is_dir()):
        h = hashlib.sha256()
        for f in sorted(x for x in sysdir.rglob("*") if x.is_file()):
            h.update(f.relative_to(SRC).as_posix().encode())
            h.update(f.read_bytes() if f.suffix != ".xlsx" else b"")  # xlsx zip metadata carries timestamps; content checked via parsed values
        digests[sysdir.name] = h.hexdigest()[:16]
    manifest = {"seed": C.SEED, "files_by_system": files, "bytes": size, "defect_counts": log.counts(), "stats": stats, "digests": digests}
    (C.TRUTH_DIR / "sources_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"done in {time.time() - t0:.0f}s  |  {sum(files.values()):,} files, {size / 1e6:.0f} MB  |  {len(d):,} logged defects")


if __name__ == "__main__":
    main()
