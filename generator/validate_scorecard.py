"""Phase 8: the validation scorecard.
Usage: python -m generator.validate_scorecard

Scores the finished system against the targets that were written down in docs/SPEC.md (section 8) and docs/DEFECT_CATALOG.md before anything was built, using the hidden
answer key: the eight success criteria, all 32 detectable defect classes, the five headline scenarios, and the three defect classes that are known to pass through.
Writes docs/SCORECARD_RESULTS.json (read by the dashboard export), docs/PHASE8_REPORT.md and docs/phase8_scorecard.png.

The targets are read from those documents' tables, never typed here, and a gate checks that every target shown on the scorecard equals the document's. Misses are published
as measured; nothing here is tuned to pass."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys

import pandas as pd

from . import config as G
from . import export_scorecard
from . import scorecard as S
from .validate import Results
from .validate_models import connect, pct, q1

DOCS = G.ROOT / "docs"


class R6(Results):
    def add(self, group, name, measured, criterion, ok):
        self.rows.append((group, name, measured, criterion, bool(ok), "GATE"))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {measured}   (need {criterion})")

    def info(self, group, name, measured):
        self.rows.append((group, name, measured, "reported", True, "INFO"))
        print(f"  [INFO] {name}: {measured}")

    @property
    def all_ok(self):
        return all(r[4] for r in self.rows if r[5] == "GATE")


def phase_row(n, prefix):
    for r in export_scorecard.parse(DOCS / f"PHASE{n}_REPORT.md"):
        if r["check"].startswith(prefix):
            return r
    raise KeyError(f"phase {n}: {prefix}")


# ------------------------------------------------------------------------------------------------------------------------- the eight criteria
def criteria(c, d, cls, scn) -> list[dict]:
    spec = S.spec_criteria()
    nums = lambda s: [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", s)]
    out = []
    byid = {r["id"]: r for r in cls}
    sc = {r["id"]: r for r in scn}

    def row(i, measured, met, evidence):
        out.append({"measure": spec[i][0], "target": spec[i][1], "measured": measured, "result": "MET" if met else "MISSED", "evidence": evidence})

    # 1 crosswalk
    prec = byid["L1"]["rate"]
    tot, res = c.execute("SELECT count(*), count(*) FILTER (WHERE item_no IS NOT NULL) FROM w.intermediate.int_legacy__resolved").fetchone()
    t1 = nums(spec[0][1])
    row(0, f"precision {100 * prec:.2f}% on {byid['L1']['n']:,} automatically resolved shared-code rows; recall {pct(res, tot):.2f}% of {tot:,} legacy rows resolved, the rest sent to review", prec * 100 >= t1[0] and pct(res, tot) >= t1[1], "Phase 4 handling checks, class L1")
    # 2 detection recall per class
    t2 = nums(spec[1][1])[0]
    below = [r for r in cls if r["rate"] * 100 < t2]
    row(1, f"{len(cls) - len(below)} of {len(cls)} detectable classes at {t2:.0f}% or better" + ("" if not below else "; below: " + ", ".join(f"{r['id']} {100 * r['rate']:.1f}%" for r in below)), not below, "per-class table below; the catalog's own per-class targets are shown there too")
    # 3 quarantine false positives
    lg = d[d.source_table == "inv_trans"]
    c.register("l_log", lg[lg.defect_code.isin(["L5", "L1"])][["source_row_key"]])
    n_leg = q1(c, "SELECT count(*) FROM w.intermediate.int_legacy__resolved")
    q = c.execute("SELECT count(*), coalesce(sum((q.trans_id NOT IN (SELECT source_row_key FROM l_log))::int), 0) FROM w.quarantine.q_legacy_trans q").fetchone()
    cl = d[d.source_table == "count_row"]
    c.register("c_log", cl[cl.defect_code.isin(["X2", "X3", "X5", "U1", "U2", "X4"])][["source_row_key"]])
    n_cnt = q1(c, "SELECT count(*) FROM w.core.fct_count")
    qc = c.execute("SELECT count(*), coalesce(sum((q.count_key NOT IN (SELECT source_row_key FROM c_log))::int), 0) FROM w.quarantine.q_count_row q").fetchone()
    ol = d[d.source_table == "sales_order_line"]
    c.register("o_log", ol[ol.defect_code.isin(["E3", "E5b", "E4", "E2"])][["source_row_key"]])
    n_ord = q1(c, "SELECT count(*) FROM w.core.fct_order_line WHERE NOT is_duplicate")
    qo = c.execute("SELECT count(*), coalesce(sum(((order_no || '|' || CAST(line_no AS VARCHAR)) NOT IN (SELECT source_row_key FROM o_log))::int), 0) FROM w.core.fct_order_line WHERE exclude_reason IS NOT NULL AND NOT is_duplicate").fetchone()
    tq, fp = q[0] + qc[0] + qo[0], int(q[1] + qc[1] + qo[1])
    good = n_leg + n_cnt + n_ord - (tq - fp)
    row(2, f"{fp} good rows rejected of {good:,} good rows = {pct(fp, good):.4f}% ({tq:,} rows quarantined, {tq - fp:,} of them truly defective)", pct(fp, good) <= nums(spec[2][1])[0], "Phase 5 conservation checks, recomputed")
    # 4 on-hand
    c.execute("""CREATE OR REPLACE TABLE cmp AS SELECT m.*, t.onhand_qty AS truth FROM w.marts.mart_stock_daily m JOIN t_sku s ON s.sku_code = m.item_no JOIN t_wh wh ON wh.warehouse_code = m.wh_code
                 JOIN t_oh t ON t.sku_id = s.sku_id AND t.warehouse_id = wh.warehouse_id AND t.snapshot_date = m.local_date""")
    n, est, rec, est_ns, susp = c.execute("""SELECT count(*), 100 * avg((est_on_hand = truth)::int), 100 * avg((book_recorded_qty = truth)::int),
                                              100 * avg((est_on_hand = truth)::int) FILTER (WHERE confidence <> 'suspect'), 100 * avg((confidence = 'suspect')::int) FROM cmp""").fetchone()
    row(3, f"{est_ns:.2f}% exact on the {100 - susp:.1f}% of {n:,} pair-days not flagged suspect ({est:.2f}% on all days; the systems' own book {rec:.2f}%)", est_ns >= nums(spec[3][1])[0], "Phase 4 stock table; Phase 7 shows the same measure decaying slowly in the live months")
    # 5 idempotency
    p = subprocess.run([sys.executable, "-m", "pytest", "tests/test_ingest.py", "-q"], cwd=G.ROOT, capture_output=True, text=True)
    m = re.search(r"(\d+) passed", p.stdout)
    passed = int(m.group(1)) if m else 0
    row(4, f"{passed} ingestion tests pass, including: a re-run changes no table in any way, a crash mid-load leaves nothing half-written, a changed file is versioned not duplicated, a late or corrupt file is handled; a repeated live tick also changes nothing (Phase 7)",
        p.returncode == 0 and passed >= 12, "tests/test_ingest.py run now; tests/test_live.py")
    # 6 backfill self-heal, 7 schema drift
    row(5, sc["S3"]["measured"], sc["S3"]["met"], "scenario S3")
    row(6, sc["S2"]["measured"], sc["S2"]["met"], "scenario S2")
    # 8 live run
    r = phase_row(7, "every run finished inside the 30-minute budget")
    row(7, r["measured"], r["result"] == "PASS", "Phase 7 report, live-clock gate")
    return out


# ------------------------------------------------------------------------------------------------------------------------- report and chart
def known_misses(d):
    out = []
    cnt = d[d.defect_code.isin(["U1", "U2", "U3"])].groupby("defect_code").size()
    for k, (what, control) in S.CONTROLS.items():
        out.append({"id": k, "what": what, "rows": int(cnt.get(k, 0)), "control": control})
    return out


def write_report(R, crit, cls, scn, miss, sha):
    mark = lambda ok: "MET" if ok else "MISSED"
    st = lambda r: {"GATE": "PASS" if r[4] else "FAIL", "INFO": "INFO"}[r[5]]
    gates = [r for r in R.rows if r[5] == "GATE"]
    ct = "\n".join(f"| {r['measure']} | {r['target']} | {r['measured']} | {r['result']} |" for r in crit)
    cs = "\n".join(f"| {r['id']} | {r['name']} | {r['n']:,} | {100 * r['rate']:.2f}% | {100 * r['target']:.1f}% ({r['kind']}) | {mark(r['met'])} | {r['wrong_repairs'] or ''} | {r['note']} |" for r in cls)
    ss = "\n".join(f"| {r['id']} | {r['name']} | {r['target']} | {r['measured']} | {mark(r['met'])} |" for r in scn)
    um = "\n".join(f"| {r['id']} | {r['what']} | {r['rows']:,} | {r['control']} |" for r in miss)
    rows = "\n".join(f"| {n} | {m} | {cr} | {st((g, n, m, cr, ok, k))} |" for g, n, m, cr, ok, k in R.rows)
    nmet = sum(r["met"] for r in cls)
    txt = ["# System 1 — Phase 8 Report: The Validation Scorecard\n",
           f"Gates: **{'ALL PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in gates)}/{len(gates)}). Scorecard: **{sum(r['result'] == 'MET' for r in crit)} of {len(crit)} success criteria met**, "
           f"**{nmet} of {len(cls)} defect classes at their catalog target**, **{sum(r['met'] for r in scn)} of {len(scn)} scenarios met**. Every miss is listed below and on the dashboard.\n",
           "## How to read this\n",
           f"The source data is synthetic, so the right answer is known for every row. This scorecard compares what the pipeline did against that answer key, using targets that were written down before anything was built "
           f"(`SPEC.md` section 8 and `DEFECT_CATALOG.md`; target text fingerprint `{sha}`). Targets are read from those documents by the code, and a gate checks that every target on the scorecard equals the document's.\n",
           "A defect is scored only if its record had been delivered by the end of history, and a class counts as handled only if the pipeline did what the catalog says it should: fixed it correctly, quarantined it, flagged it, or sent it to a person. "
           "Wrong repairs are counted and shown beside the rate; the pass mark is the catalog's target for the rate.\n",
           "## The eight success criteria (SPEC section 8)\n", "| Measure | Target | Measured | Result |\n|---|---|---|---|", ct,
           "\n## The five headline scenarios\n", "| ID | Scenario | Target | Measured | Result |\n|---|---|---|---|---|", ss,
           f"\n## Every detectable defect class ({len(cls)})\n", "| ID | Defect | Scored | Handled right | Catalog target | Result | Wrong repairs | What was measured |\n|---|---|---|---|---|---|---|---|", cs,
           "\n## Known misses: defects that pass through by design\n", "The pipeline cannot see these, and says so. Each has a recommended control that is a business process, not a pipeline fix.\n",
           "| ID | What | Rows | Recommended control |\n|---|---|---|---|", um,
           "\n## Honest notes\n",
           "- **Two readings of 'detection recall'.** The spec asks for 95% on every class; the catalog sets a target per class (some lower, such as 85% for cases-counted-as-each). Both are shown. Against the spec's flat bar, the classes that miss are listed in criterion 2; against the catalog's own targets the misses are the rows marked MISSED in the class table.\n",
           "- **Two gaps were closed while building this scorecard, and one was not.** Scoring every class showed that price-override conflicts (X6) were staged but never flagged, and that missing piece counts (F5) were not marked, so both were built (a conflict list that goes to purchasing, and an explicit missing-pieces flag) before being scored. "
           "The stock table also now marks a warehouse's estimates as suspect while its feed is silent, which the outage scenario required and a point-in-time replay verifies. The Albuquerque item re-keys (E1) are not fixable with the evidence available and remain a miss.\n",
           "- **The stock-accuracy target is missed, and the live months are lower still.** See criterion 4 and Phase 7: unrecorded shrink accumulates between counts, so the lever is how often items are counted.\n",
           "- **The 'manual hours replaced' figure is a modeled estimate**, not a measurement, and is labelled that way on the dashboard.\n",
           "- **Numbers here are as of the end of history (2026-09-30).** The live clock leaves them untouched; the live period has its own results in the Phase 7 report.\n",
           "\n## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (DOCS / "PHASE8_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def chart(cls, crit):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(15, 7), gridspec_kw={"width_ratios": [1.5, 1]})
    k = sorted(cls, key=lambda r: r["rate"] - r["target"])
    y = range(len(k))
    ax[0].barh(list(y), [100 * r["rate"] for r in k], color=["#2e8b57" if r["met"] else "#c0392b" for r in k], height=0.65)
    ax[0].scatter([100 * r["target"] for r in k], list(y), marker="|", s=220, color="black", zorder=3, label="catalog target")
    ax[0].set_yticks(list(y), [f"{r['id']}  {r['name'][:34]}" for r in k], fontsize=7.5)
    ax[0].set_xlim(80, 100.5)
    ax[0].set_xlabel("share of injected defects handled as the catalog says (%)")
    ax[0].set_title("Every defect class against its catalog target")
    ax[0].legend(loc="lower left", fontsize=8)
    names = [f"{i + 1}. {r['measure'][:46]}" for i, r in enumerate(crit)]
    ax[1].barh(range(len(crit)), [1] * len(crit), color=["#2e8b57" if r["result"] == "MET" else "#c0392b" for r in crit])
    for i, r in enumerate(crit):
        ax[1].text(0.5, i, r["result"], ha="center", va="center", color="white", fontweight="bold")
    ax[1].set_yticks(range(len(crit)), names, fontsize=8)
    ax[1].set_xticks([])
    ax[1].invert_yaxis()
    ax[1].set_title("The eight success criteria")
    fig.suptitle("Phase 8: the validation scorecard (all data synthetic; misses in red)", fontsize=12)
    fig.tight_layout()
    fig.savefig(DOCS / "phase8_scorecard.png", dpi=110)


def sections(crit, cls, scn, miss, sha):
    return {"criteria": crit, "classes": cls, "scenarios": scn, "known_misses": miss, "targets_sha": sha}


def main():
    R = R6()
    c = connect()
    d = pd.read_parquet(G.TRUTH_DIR / "truth_defects.parquet")
    print("Scoring the defect classes and scenarios")
    cls = S.classes(c, d)
    scn = S.scenarios(c, d)
    crit = criteria(c, d, cls, scn)
    miss = known_misses(d)
    spec_txt = "\n".join(f"{a}|{b}" for a, b in S.spec_criteria()) + "\n" + "\n".join(f"{k}|{v[0]}|{v[1]}" for k, v in sorted(S.catalog_targets().items()))
    sha = hashlib.sha256(spec_txt.encode()).hexdigest()[:12]

    print("Gates")
    # the targets on the scorecard are the documents' targets
    sp = S.spec_criteria()
    R.add("A", "the eight criteria and their targets on the scorecard are exactly SPEC section 8", f"{len(crit)} criteria; targets equal the document's: {[(r['measure'], r['target']) for r in crit] == sp}", "identical", [(r["measure"], r["target"]) for r in crit] == sp and len(sp) == 8)
    ct = S.catalog_targets()
    R.add("A", "every class target on the scorecard is the catalog's", f"{len(cls)} classes; {sum(abs(r['target'] - ct[r['id']][0]) < 1e-9 for r in cls)} equal the catalog's target", "all equal", all(abs(r["target"] - ct[r["id"]][0]) < 1e-9 for r in cls))
    logged = set(d.defect_code)
    accounted = {r["id"] for r in cls} | set(S.CONTROLS) | {"S2", "S3", "S1", "S4", "S5"}
    gaps = sorted(logged - accounted)
    R.add("A", "every defect class in the answer key is on the scorecard, as a scored class, a known miss or a scenario", f"{len(logged)} codes in the log; not accounted for: {gaps or 'none'}", "none missing", not gaps)
    R.add("A", "no scored class is empty (every class had defects to find in the delivered data)", f"smallest class {min(cls, key=lambda r: r['n'])['id']} with {min(r['n'] for r in cls)} instances", ">= 3 each", all(r["n"] >= 3 for r in cls))
    # consistency with what the earlier phases published
    p4 = phase_row(4, "SPEC target: estimate exact on")
    crit4 = next(r for r in crit if r["measure"].startswith("Reconstructed"))
    R.add("A", "the on-hand figure equals the Phase 4 report's", f"scorecard {crit4['measured'][:48]}...; Phase 4: {p4['measured'][:60]}", "same percentage", re.search(r"([\d.]+)%", crit4["measured"]).group(1) == re.search(r"([\d.]+)%", p4["measured"]).group(1))
    w5 = phase_row(4, "W5 mis-keyed receipts")
    cw5 = next(r for r in cls if r["id"] == "W5")
    R.add("A", "class results equal the Phase 4 handling checks they came from (W5 and F7 counts)", f"W5: scorecard {cw5['ok']} of {cw5['n']}, Phase 4 '{w5['measured'][:36]}'", "same counts", f"{cw5['ok']} of {cw5['n']}" in w5["measured"])
    f7 = phase_row(4, "F7 duplicate carrier charge lines")
    cf7 = next(r for r in cls if r["id"] == "F7")
    R.add("A", "F7 recoverable-dollar count equals Phase 4's", f"scorecard {cf7['ok']} of {cf7['n']}; Phase 4: {f7['measured'][:40]}", "same counts", f"{cf7['ok']} of {cf7['n']}" in f7["measured"])
    # nothing hidden
    misses = [r["id"] for r in cls if not r["met"]] + [r["id"] for r in scn if not r["met"]] + [str(i + 1) for i, r in enumerate(crit) if r["result"] != "MET"]
    R.info("A", "everything that missed, in one place", f"classes {[r['id'] for r in cls if not r['met']]}; scenarios {[r['id'] for r in scn if not r['met']]}; criteria {[i + 1 for i, r in enumerate(crit) if r['result'] != 'MET']}")
    # deterministic: scoring twice gives identical results
    cls2 = S.classes(c, d)
    same = json.dumps(cls, default=str, sort_keys=True) == json.dumps(cls2, default=str, sort_keys=True)
    R.add("A", "scoring is deterministic: a second run gives identical results", "identical" if same else "DIFFERENT", "identical", same)
    c.close()
    (DOCS / "SCORECARD_RESULTS.json").write_text(json.dumps(sections(crit, cls, scn, miss, sha), indent=1, default=str), encoding="utf-8")
    write_report(R, crit, cls, scn, miss, sha)
    chart(cls, crit)
    export_scorecard.main()
    leaks = re.search(r"truth_[a-z_]+|state_end_of_history", (G.ROOT / "dashboard" / "data" / "scorecard.json").read_text(encoding="utf-8"))
    R.add("B", "the published scorecard contains scores only: no answer-key table names", "none found" if not leaks else leaks.group(0), "none", not leaks)
    write_report(R, crit, cls, scn, miss, sha)
    gates = [r for r in R.rows if r[5] == "GATE"]
    print(f"\n{sum(r[4] for r in gates)}/{len(gates)} gates passed; criteria {sum(r['result'] == 'MET' for r in crit)}/{len(crit)} met, classes {sum(r['met'] for r in cls)}/{len(cls)}, scenarios {sum(r['met'] for r in scn)}/{len(scn)}")
    sys.exit(0 if R.all_ok else 1)


if __name__ == "__main__":
    main()
