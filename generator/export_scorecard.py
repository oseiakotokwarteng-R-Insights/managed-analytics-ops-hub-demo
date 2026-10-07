"""Collects the published results of every phase gate into dashboard/data/scorecard.json.
Usage: python -m generator.export_scorecard

It parses the check tables of docs/PHASE*_REPORT.md (written by the truth-aware validators), so the dashboard shows exactly what was measured, misses included.
The answer key itself is never published, only the scores."""
from __future__ import annotations

import json
import re

from . import config as G

PHASES = {
    1: "Synthetic universe", 2: "Five source systems", 3: "Raw-layer ingestion", 4: "Modeling and the stock table", 5: "Data quality and observability", 6: "Dashboard", 7: "Live clock", 8: "Validation scorecard", 9: "Packaging",
}


def parse(path):
    rows, in_t = [], False
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("| Check | Measured | Criterion | Result |"):
            in_t = True
            continue
        if in_t:
            if not ln.startswith("|"):
                in_t = False
                continue
            if ln.startswith("|---"):
                continue
            c = [x.strip() for x in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]
            if len(c) >= 4:
                rows.append({"check": c[0], "measured": c[1], "criterion": c[2], "result": c[3]})
    return rows


def main():
    out = {"phases": [], "headlines": {}}
    for n, name in PHASES.items():
        p = G.ROOT / "docs" / f"PHASE{n}_REPORT.md"
        if not p.exists():
            continue
        rows = parse(p)
        out["phases"].append({"phase": n, "name": name, "checks": rows,
                              "pass": sum(r["result"] == "PASS" for r in rows), "fail": sum(r["result"] == "FAIL" for r in rows),
                              "met": sum(r["result"] == "MET" for r in rows), "missed": sum(r["result"] == "MISSED" for r in rows)})
    # headline numbers the dashboard quotes (parsed from the Phase 4 checks)
    p4 = {r["check"]: r for p in out["phases"] if p["phase"] == 4 for r in p["checks"]}
    k = next((v for c, v in p4.items() if c.startswith("the estimate beats the systems")), None)
    if k:
        m = re.search(r"recorded book exact on ([\d.]+)%.*?reconstructed estimate ([\d.]+)%", k["measured"])
        if m:
            out["headlines"]["recorded_exact"], out["headlines"]["estimate_exact"] = float(m.group(1)), float(m.group(2))
    k = next((v for c, v in p4.items() if c.startswith("accuracy decays")), None)
    if k:
        out["headlines"]["decay"] = [{"label": a.strip(), "exact": float(b)} for a, b in re.findall(r"(never counted|[\d>\-]+ d): ([\d.]+)%", k["measured"])]
    k = next((v for c, v in p4.items() if c.startswith("SPEC target: estimate exact")), None)
    if k:
        out["headlines"]["stock_target"] = {"measured": k["measured"], "criterion": k["criterion"], "result": k["result"]}
    k = next((v for c, v in p4.items() if c.startswith("calibration by confidence tier")), None)
    if k:
        out["headlines"]["tiers"] = [{"tier": a, "exact": float(b), "share": float(c)} for a, b, c in re.findall(r"(\w+): ([\d.]+)% exact on ([\d.]+)% of days", k["measured"])]
    sec = G.ROOT / "docs" / "SCORECARD_RESULTS.json"
    if sec.exists():  # the per-criterion, per-class and per-scenario results written by generator.validate_scorecard
        out.update(json.loads(sec.read_text(encoding="utf-8")))
    (G.ROOT / "dashboard" / "data").mkdir(parents=True, exist_ok=True)
    (G.ROOT / "dashboard" / "data" / "scorecard.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print("scorecard:", ", ".join(f"P{p['phase']} {p['pass']}P/{p['fail']}F/{p['met']}M/{p['missed']}X" for p in out["phases"]))


if __name__ == "__main__":
    main()
