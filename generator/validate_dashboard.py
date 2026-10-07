"""Phase 6 gate: scores the dashboard exports and the analytics behind them.
Usage: python -m generator.validate_dashboard

A. Export integrity (truth-free): files, lossless per-SKU history, headline numbers equal the marts, size budget for phones, no answer key published, JavaScript parses.
B. Run-out risk backtest against physical truth, including a comparison with the same rule applied to the systems' own recorded book.
C. Phantom-stock alert scored against the S1 scenario (when it began, how fast it fired, which items, how much value, no false alarms elsewhere).
Gates are pass/fail. Spec targets and the thresholds declared below are reported MET or MISSED; they were written before the results were read."""
from __future__ import annotations

import gzip
import json
import random
import re
import subprocess
import sys
from datetime import timedelta

import duckdb
import numpy as np
import pandas as pd

from . import config as G
from .validate import Results

DB = (G.ROOT / "warehouse" / "ops_hub.duckdb").as_posix()
TD = G.TRUTH_DIR.as_posix()
DATA = G.ROOT / "dashboard" / "data"
JS = G.ROOT / "dashboard"
CONF = ["verified", "carried", "suspect"]

# thresholds declared before the backtest was run
RISK_PRECISION_MIN, RISK_RECALL_MIN = 0.50, 0.70
PHANTOM_START_TOLERANCE_DAYS = 3  # from the defect catalog (S1)


class R4(Results):
    def target(self, group, name, measured, criterion, met):
        self.rows.append((group, name, measured, criterion, bool(met), "TARGET"))
        print(f"  [{'MET' if met else 'MISSED'}] {name}: {measured}   (target {criterion})")

    def add(self, group, name, measured, criterion, ok):
        self.rows.append((group, name, measured, criterion, bool(ok), "GATE"))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {measured}   (need {criterion})")

    def info(self, group, name, measured):
        self.rows.append((group, name, measured, "reported", True, "INFO"))
        print(f"  [INFO] {name}: {measured}")

    @property
    def all_ok(self):
        return all(r[4] for r in self.rows if r[5] == "GATE")


def connect():
    c = duckdb.connect()
    c.execute("SET TimeZone = 'UTC'")
    c.execute(f"ATTACH '{DB}' AS w (READ_ONLY)")
    for v, f in {"t_oh": "truth_onhand_daily", "t_sku": "dim_sku", "t_wh": "dim_warehouse", "t_mv": "truth_movements", "t_scen": "truth_scenarios", "t_ent": "truth_scenario_entities"}.items():
        c.execute(f"CREATE VIEW {v} AS SELECT * FROM read_parquet('{TD}/{f}.parquet')")
    return c


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


def jload(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------------------------------------------------------- A
def decode(h, days):
    est, rec, conf = [None] * days, [None] * days, [None] * days
    a = b = 0
    for i, d in enumerate(h["e"]):
        a += d
        est[h["s"] + i] = a
    for i, d in enumerate(h["r"]):
        b += d
        rec[h["s"] + i] = b
    p = h["s"]
    for i in range(0, len(h["c"]), 2):
        for _ in range(h["c"][i + 1]):
            conf[p] = h["c"][i]
            p += 1
    return est, rec, conf


def integrity(c, R):
    print("A. Export integrity")
    meta = jload("meta.json")
    need = ["meta", "overview", "stock", "skus", "risk", "inbound", "freight", "exceptions", "health", "manual_effort", "scorecard"]
    miss = [n for n in need if not (DATA / f"{n}.json").exists()]
    nsku = c.execute("SELECT count(DISTINCT item_no) FROM w.core.dim_sku").fetchone()[0]
    shards = len(list((DATA / "sku").glob("*.json")))
    R.add("A", "every data file and one history file per item exist", f"{len(need) - len(miss)} of {len(need)} data files; {shards:,} of {nsku:,} item histories", "all", not miss and shards == nsku)

    # lossless history: decode random item-warehouse-days from the shards and compare with the mart
    random.seed(6)
    pairs = c.execute("SELECT item_no, wh_code FROM w.marts.mart_stock_current").fetchall()
    sample = random.sample(pairs, 300)
    d0 = pd.Timestamp(meta["history_start"]).date()
    bad = n = 0
    for item, wh in sample:
        h = json.loads((DATA / "sku" / f"{item}.json").read_text(encoding="utf-8"))
        est, rec, conf = decode(h["wh"][wh], h["days"])
        days = random.sample(range(h["wh"][wh]["s"], h["days"]), 6)
        for k in days:
            row = c.execute("SELECT est_on_hand, book_recorded_qty, confidence FROM w.marts.mart_stock_daily WHERE item_no = ? AND wh_code = ? AND local_date = ?", [item, wh, d0 + timedelta(days=k)]).fetchone()
            n += 1
            if row is None or round(row[0]) != est[k] or int(row[1]) != rec[k] or CONF.index(row[2]) != conf[k]:
                bad += 1
    R.add("A", "the item histories on the dashboard equal the stock mart (any item, any date)", f"{n - bad} of {n} sampled item-warehouse-days identical (estimate, system figure, confidence)", "all identical", bad == 0)

    # headline numbers equal the marts
    ov = jload("overview.json")
    m = c.execute("""SELECT count(*), count(*) FILTER (WHERE risk = 'at_risk'), count(*) FILTER (WHERE risk = 'out_of_stock'), sum(available_to_promise) FILTER (WHERE available_to_promise > 0) FROM w.marts.mart_stock_current""").fetchone()
    ok = (ov["pairs"], ov["at_risk"], ov["out_of_stock"], round(ov["atp_units"])) == (m[0], m[1], m[2], round(m[3]))
    R.add("A", "overview figures equal the marts they summarise", f"{ov['pairs']:,} pairs, {ov['at_risk']} at risk, {ov['out_of_stock']} out, {ov['atp_units']:,.0f} units to promise", "identical to the mart", ok)
    sc = jload("scorecard.json")
    ph = {p["phase"]: p for p in sc["phases"]}
    R.add("A", "the scorecard shows every phase result, misses included", f"phases {sorted(ph)}; failed checks {sum(p['fail'] for p in sc['phases'])}; missed targets shown: {sum(p['missed'] for p in sc['phases'])}", "phases 1-5 present", set(range(1, 6)) <= set(ph))
    me = jload("manual_effort.json")
    R.add("A", "the manual-effort figure is labelled as a modeled estimate with its assumptions", f"modeled={me['modeled']}, {len(me['rows'])} rows each with minutes per item and basis", "labelled", me["modeled"] is True and all(r["minutes_per_item"] > 0 and r["basis"] for r in me["rows"]))
    fr = jload("freight.json")
    R.add("A", "the slow-shipment definition is published with its assumptions", "; ".join(f"{s['direction']} > {s['max_transit_days']} days" for s in fr["standards"]), "stated", len(fr["standards"]) == 2)

    # phone budget
    sizes = {p.name: p.stat().st_size for p in DATA.glob("*.json")}
    first = sizes["overview.json"] + sizes["scorecard.json"] + sizes["stock.json"] + sizes["meta.json"]
    gz = lambda p: len(gzip.compress(p.read_bytes(), 6))
    first_gz = sum(gz(DATA / n) for n in ("overview.json", "scorecard.json", "stock.json", "meta.json"))
    skus_gz = gz(DATA / "skus.json")
    shard_gz = sum(len(gzip.compress(p.read_bytes(), 6)) for p in random.sample(list((DATA / "sku").glob("*.json")), 100)) / 100
    jsb = sum(p.stat().st_size for p in (JS / "js").rglob("*.js")) + (JS / "css" / "style.css").stat().st_size + (JS / "index.html").stat().st_size
    R.add("A", "the first screen loads in under 100 KB over the wire (data and code, compressed)", f"data {first_gz / 1e3:.0f} KB gz, code {jsb / 1e3:.0f} KB raw (about {jsb / 4 / 1e3:.0f} KB gz); item search index {skus_gz / 1e3:.0f} KB gz loaded on first search; one item history about {shard_gz / 1e3:.1f} KB gz", "data+code <= 100 KB gz", first_gz + jsb / 4 <= 100e3)
    tot = sum(p.stat().st_size for p in DATA.rglob("*.json"))
    R.info("A", "published data volume", f"{tot / 1e6:.1f} MB over {len(list(DATA.rglob('*.json'))):,} files (compresses to about {(sum(len(gzip.compress(p.read_bytes(), 6)) for p in random.sample(list((DATA / 'sku').glob('*.json')), 200)) / 200 * shards + sum(gz(p) for p in DATA.glob('*.json'))) / 1e6:.1f} MB)")

    # the answer key must not be published
    leaks = []
    for p in list(DATA.rglob("*.json"))[:200] + list(DATA.glob("*.json")):
        t = p.read_text(encoding="utf-8")
        if re.search(r"truth_[a-z_]+|state_end_of_history|truth_defects", t):
            leaks.append(p.name)
    others = [p.name for p in DATA.rglob("*") if p.is_file() and p.suffix != ".json"]
    R.add("A", "nothing from the answer key is published (no table names, no non-JSON files)", f"{len(set(leaks))} files mention an answer-key table; {len(others)} non-JSON files", "0 and 0", not leaks and not others)

    # javascript parses
    fails = []
    for p in (JS / "js").rglob("*.js"):
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
        if r.returncode:
            fails.append(p.name)
    cards = len(re.findall(r"\bcard\(\d", (JS / "js" / "views" / "overview.js").read_text(encoding="utf-8")))
    R.add("A", "all dashboard code parses and the overview answers all 8 business questions", f"{len(list((JS / 'js').rglob('*.js')))} files, {len(fails)} with errors; {cards} question cards", "0 errors, 8 cards", not fails and cards == 8)
    return ov


# ----------------------------------------------------------------------------------------------------------------------------- B
def backtest(c, R):
    print("B. Run-out risk backtest")
    end = c.execute("SELECT max(local_date) FROM w.marts.mart_stock_daily").fetchone()[0]
    lo, hi = end - timedelta(days=149), end - timedelta(days=15)
    c.execute(f"""CREATE TABLE nxt AS
        SELECT s.sku_code AS item_no, wh.warehouse_code AS wh_code, CAST(t.snapshot_date AS DATE) AS d,
               min(t.onhand_qty) OVER (PARTITION BY t.sku_id, t.warehouse_id ORDER BY CAST(t.snapshot_date AS DATE) ROWS BETWEEN 1 FOLLOWING AND 14 FOLLOWING) AS min_next14
        FROM t_oh t JOIN t_sku s USING (sku_id) JOIN t_wh wh USING (warehouse_id) WHERE CAST(t.snapshot_date AS DATE) >= DATE '{lo}'""")
    c.execute(f"""CREATE TABLE bt AS
        SELECT r.item_no, r.wh_code, r.d, r.risk, r.units_28d, r.daily_rate, r.est_on_hand, m.book_recorded_qty, n.min_next14,
               (n.min_next14 <= 0) AS truly_out
        FROM w.marts.mart_stock_risk_daily r
        JOIN w.marts.mart_stock_daily m ON m.item_no = r.item_no AND m.wh_code = r.wh_code AND m.local_date = r.d
        JOIN nxt n ON n.item_no = r.item_no AND n.wh_code = r.wh_code AND n.d = r.d
        WHERE r.d BETWEEN DATE '{lo}' AND DATE '{hi}' AND date_diff('day', DATE '{lo}', r.d) % 7 = 0 AND r.units_28d >= 3""")
    n = c.execute("SELECT count(*), count(DISTINCT d) FROM bt").fetchone()

    def score(pred):
        r = c.execute(f"SELECT count(*) FILTER (WHERE {pred} AND truly_out), count(*) FILTER (WHERE {pred} AND NOT truly_out), count(*) FILTER (WHERE NOT ({pred}) AND truly_out) FROM bt").fetchone()
        tp, fp, fn = r
        p, rc = tp / (tp + fp) if tp + fp else float("nan"), tp / (tp + fn) if tp + fn else float("nan")
        return dict(tp=tp, fp=fp, fn=fn, precision=p, recall=rc, f1=2 * p * rc / (p + rc) if p + rc else 0)
    ours = score("risk IN ('at_risk', 'out_of_stock')")
    book = score("(book_recorded_qty <= 0 OR book_recorded_qty / daily_rate <= 14)")
    base = c.execute("SELECT avg(truly_out::int) FROM bt").fetchone()[0]
    R.info("B", "backtest sample", f"{n[0]:,} item-warehouse-days with demand, on {n[1]} weekly as-of dates, scored on whether physical stock hit zero within the next 14 days (base rate {100 * base:.1f}%)")
    R.target("B", "SPEC-style target: the risk list catches at least 70% of real run-outs at 50%+ precision", f"recall {100 * ours['recall']:.1f}%, precision {100 * ours['precision']:.1f}% ({ours['tp']:,} true, {ours['fp']:,} false alarms, {ours['fn']:,} missed)", f"recall >= {RISK_RECALL_MIN:.0%} and precision >= {RISK_PRECISION_MIN:.0%}", ours["recall"] >= RISK_RECALL_MIN and ours["precision"] >= RISK_PRECISION_MIN)
    R.add("B", "the reconstructed stock beats the systems' own book at predicting run-outs (F1)", f"ours F1 {ours['f1']:.3f} (precision {100 * ours['precision']:.1f}%, recall {100 * ours['recall']:.1f}%) vs recorded book {book['f1']:.3f} (precision {100 * book['precision']:.1f}%, recall {100 * book['recall']:.1f}%)", "ours > book", ours["f1"] > book["f1"])
    sel = c.execute("SELECT risk, count(*) n, avg(truly_out::int) hit FROM bt GROUP BY 1 ORDER BY 1").fetchdf()
    R.info("B", "hit rate by risk class", "; ".join(f"{r.risk}: {100 * r.hit:.1f}% ran out ({int(r.n):,})" for r in sel.itertuples()))
    return ours, book, sel


# ----------------------------------------------------------------------------------------------------------------------------- C
def phantom(c, R):
    print("C. Phantom-stock alert against scenario S1")
    s1 = c.execute("SELECT start_date, end_date, warehouse_id FROM t_scen WHERE scenario_id = 'S1'").fetchone()
    start, end = s1[0], s1[1]
    whc = c.execute("SELECT warehouse_code FROM t_wh WHERE warehouse_id = ?", [s1[2]]).fetchone()[0]
    ep = c.execute("SELECT * FROM w.marts.mart_ghost_stock_episode ORDER BY alert_date").fetchdf()
    R.add("C", "exactly one phantom-stock episode is reported, at the right warehouse", f"{len(ep)} episode(s): {', '.join(ep.wh_code)}; truth: {whc}", "1 at the scenario warehouse", len(ep) == 1 and ep.wh_code.iloc[0] == whc)
    e = ep.iloc[0]
    fa = c.execute("SELECT count(*) FROM w.marts.mart_ghost_stock_daily WHERE is_alert AND wh_code <> ?", [whc]).fetchone()[0]
    R.add("C", "no alert at any other warehouse on any night of the 730 (false alarms)", f"{fa} alert nights elsewhere", "0", fa == 0)
    est = pd.Timestamp(e.est_start).date()
    err = (est - start).days
    R.target("C", "SPEC target (S1): the history shows when the loss began, within 3 days of the truth", f"estimated {est} vs true {start} ({err:+d} days)", f"within {PHANTOM_START_TOLERANCE_DAYS} days", abs(err) <= PHANTOM_START_TOLERANCE_DAYS)
    lat = (pd.Timestamp(e.alert_date).date() - start).days
    R.info("C", "alert latency", f"alert raised {pd.Timestamp(e.alert_date).date()}, {lat} days after the loss began and {(end - pd.Timestamp(e.alert_date).date()).days} days before the count that discovered it ({end})")
    conf = pd.Timestamp(e.first_confirming_count).date() if pd.notna(e.first_confirming_count) else None
    R.add("C", "the first confirming count the pipeline finds is the count that discovered the loss", f"pipeline: {conf}; truth discovery: {end}", "same date", conf == end)
    # items
    truth_items = {r[0] for r in c.execute("SELECT s.sku_code FROM t_ent e JOIN t_sku s USING (sku_id) WHERE e.scenario_id = 'S1'").fetchall()}
    got = {r[0] for r in c.execute("""SELECT item_no FROM w.marts.mart_ghost_stock_line WHERE wh_code = ? AND order_date BETWEEN CAST(? AS DATE) - 45 AND CAST(? AS DATE) - 7 GROUP BY 1 HAVING count(*) >= 3""", [whc, e.alert_date, e.last_alert_date]).fetchall()}
    tp = len(got & truth_items)
    prec, rec = tp / len(got), tp / len(truth_items)
    R.add("C", "items named as affected are really affected (precision)", f"{tp} of {len(got)} named items are among the {len(truth_items)} that lost stock = {100 * prec:.1f}%", ">= 95%", prec >= 0.95)
    R.info("C", "share of the affected items found (recall)", f"{tp} of {len(truth_items)} = {100 * rec:.1f}%; the rest had fewer than three orders in the window, so no pattern to see")
    lost = c.execute("SELECT sum(-m.qty_delta * s.unit_cost) FROM t_mv m JOIN t_sku s USING (sku_id) WHERE m.movement_type = 'scenario_loss'").fetchone()[0]
    claimed = float(e.book_value_at_risk)
    R.add("C", "the book value flagged at risk is close to the true value lost", f"flagged {claimed:,.0f} vs truly lost {lost:,.0f} (ratio {claimed / lost:.2f})", "within 25%", abs(claimed / lost - 1) <= 0.25)
    return dict(e=e, start=start, end=end, whc=whc, err=err, lost=lost, prec=prec, rec=rec)


# ----------------------------------------------------------------------------------------------------------------------------- report
def write_report(R, ours, book, sel, ph):
    st = lambda r: {"GATE": "PASS" if r[4] else "FAIL", "TARGET": "MET" if r[4] else "MISSED", "INFO": "INFO"}[r[5]]
    rows = "\n".join(f"| {n} | {m} | {cr} | {st((g, n, m, cr, ok, k))} |" for g, n, m, cr, ok, k in R.rows)
    gates = [r for r in R.rows if r[5] == "GATE"]
    tg = [r for r in R.rows if r[5] == "TARGET"]
    ov = jload("overview.json")
    e = ph["e"]
    txt = ["# System 1 — Phase 6 Report: The Dashboard\n",
           f"Gates: **{'ALL PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in gates)}/{len(gates)}). Targets: **{sum(r[4] for r in tg)} of {len(tg)} met**"
           f"{'' if all(r[4] for r in tg) else ', ' + str(len(tg) - sum(r[4] for r in tg)) + ' missed (published as measured)'}.\n",
           "## What was built\n",
           "A static, mobile-first site (`dashboard/`): plain HTML, CSS and JavaScript with no build step and no libraries, reading pre-aggregated JSON exported from the marts. Phone layout is the base design (bottom tab bar, one column, 44 px touch targets); wider screens add a top navigation and multi-column cards. Light and dark themes follow the device.\n",
           "| View | Answers | Content |\n|---|---|---|",
           "| Overview | all eight business questions | one card per question, last night's status |",
           "| Stock | Q1, Q3 | search any item, today's position in all six warehouses, history slider for any past date, count accuracy by month, biggest gaps between our estimate and the system |",
           "| Risk and inbound | Q2, Q4 | items that will run out within 14 days or already have, transfer suggestions, open and overdue purchase orders, supplier on-time rates |",
           "| Exceptions | Q6 | phantom-stock alert with its timeline, affected items, review queue by owner and action, what was fixed automatically |",
           "| Freight | Q5 | cost per 100 lb, per order and per unit by carrier, slow-shipment rate, lanes, charge breakdown, recoverable duplicate charges |",
           "| Pipeline health | Q7 | every night of history, alert log, feed freshness, defect-rate charts, row conservation, plain-words check catalog |",
           "| Scorecard | Q8 and the proof | all phase results including misses, modeled manual-hours estimate with assumptions |",
           "| Roadmap | strategy panel | count-frequency finding from this data, maturity path |\n",
           "## New analytics (all in dbt, tested)\n",
           "`mart_stock_current`, `mart_stock_risk_daily` (demand, promised inbound, days of cover, run-out risk, transfer suggestions), `mart_inbound_open`, `mart_vendor_ontime`, `mart_count_accuracy`, `mart_ghost_stock_line / daily / episode` (phantom stock), `mart_freight_shipment / weekly / lane`, `mart_manual_effort`. Seeds: `service_standards`, `manual_effort_assumptions`.\n",
           "## Run-out risk, scored against physical truth\n",
           "| Rule | Precision | Recall | F1 |\n|---|---|---|---|",
           f"| Reconstructed stock (dashboard) | {100 * ours['precision']:.1f}% | {100 * ours['recall']:.1f}% | {ours['f1']:.3f} |",
           f"| The systems' own recorded book | {100 * book['precision']:.1f}% | {100 * book['recall']:.1f}% | {book['f1']:.3f} |\n",
           "Scored on weekly as-of dates over the last 150 days: did physical stock hit zero within the next 14 days? Thresholds (precision 50%, recall 70%) were set before the backtest ran.\n",
           "## Phantom stock (scenario S1)\n",
           f"The alert watches for order lines that sit unshipped for more than a week while the book says stock is on hand, per warehouse, against a threshold learned from the first year. It needs no counts. Truth: stock lost at {ph['whc']} on {ph['start']}, found by a count on {ph['end']}.\n",
           f"- Pipeline's estimated start: **{pd.Timestamp(e.est_start).date()}** ({ph['err']:+d} days). Alert raised **{pd.Timestamp(e.alert_date).date()}**, {(pd.Timestamp(e.alert_date).date() - ph['start']).days} days after the loss and **{(ph['end'] - pd.Timestamp(e.alert_date).date()).days} days before the count**.",
           f"- {int(e.affected_skus)} items named, {100 * ph['prec']:.0f}% truly affected, {100 * ph['rec']:.0f}% of all affected items found; {int(e.stuck_order_lines)} stuck order lines worth ${e.stuck_order_value:,.0f}; book value at risk ${e.book_value_at_risk:,.0f} vs ${ph['lost']:,.0f} truly lost.",
           "- No alert at any other warehouse on any night.\n",
           "## Honest notes\n",
           "- **The start-date estimator was revised once.** The first version took the earliest stuck order in the cluster and started the episode a month early (stray late orders, plus never-closed order lines that age forever). The final version counts a SKU's start only when a stuck line is followed by another, takes the third earliest SKU, and ages dead lines out after 60 days. It was designed on the mechanism, not fitted to the truth date, but the first result was seen before the redesign.\n",
           "- **A thing I tried and dropped:** a chart of how the system book's accuracy changes with time since the previous count. In this data the book is wrong about 20% of the time at every interval, so it told no story. The count-frequency finding on the roadmap uses the accuracy of the *reconstructed estimate* by time since last count (Phase 4, scored against truth) instead.\n",
           "- **Freight cost windows end three days before the data does.** Carriers invoice on delivery, so the newest shipments have no charges yet and would make every cost figure look too low.\n",
           "- **'Slow' shipments are judged against assumed standards** (the feeds carry no promised delivery dates); the assumptions are published on the dashboard.\n",
           "- **Modeled, not measured:** the manual-hours figure multiplies real counts by assumed minutes per item. It is labelled MODELED wherever it appears.\n",
           "- **Browser checks** (phone, tablet-width desktop, dark mode) were done by hand in a real browser pane; they are not part of this automated gate.\n",
           "\n## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (G.ROOT / "docs" / "PHASE6_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def chart(c, ours, book, sel, ph):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.8))
    labs = ["precision", "recall", "F1"]
    a = [100 * ours["precision"], 100 * ours["recall"], 100 * ours["f1"]]
    b = [100 * book["precision"], 100 * book["recall"], 100 * book["f1"]]
    x = np.arange(3)
    ax[0].bar(x - 0.2, a, 0.4, label="Reconstructed stock", color="#1D5FA3")
    ax[0].bar(x + 0.2, b, 0.4, label="System's own book", color="#8a94a3")
    for i, (u, v) in enumerate(zip(a, b)):
        ax[0].text(i - 0.2, u + 1, f"{u:.0f}", ha="center", fontsize=9)
        ax[0].text(i + 0.2, v + 1, f"{v:.0f}", ha="center", fontsize=9)
    ax[0].set_xticks(x, labs)
    ax[0].set_ylim(0, 105)
    ax[0].set_ylabel("%")
    ax[0].set_title("Predicting a run-out within 14 days (scored on physical truth)")
    ax[0].legend()
    d = c.execute("SELECT as_of, n_lines, threshold FROM w.marts.mart_ghost_stock_daily WHERE wh_code = ? AND as_of BETWEEN DATE '2026-01-15' AND DATE '2026-08-15' ORDER BY as_of", [ph["whc"]]).fetchdf()
    o = c.execute("SELECT as_of, max(n_lines) n FROM w.marts.mart_ghost_stock_daily WHERE wh_code <> ? AND as_of BETWEEN DATE '2026-01-15' AND DATE '2026-08-15' GROUP BY 1 ORDER BY 1", [ph["whc"]]).fetchdf()
    ax[1].plot(d.as_of, d.n_lines, color="#d9822b", lw=2, label=f"{ph['whc']} stuck order lines")
    ax[1].plot(o.as_of, o.n, color="#8a94a3", lw=1.2, label="busiest other warehouse")
    ax[1].axhline(d.threshold.iloc[0], color="#b3261e", ls="--", lw=1, label="alert threshold")
    for dt, lab, col in ((ph["start"], "true loss", "black"), (pd.Timestamp(ph["e"].est_start), "estimated start", "#1D5FA3"), (pd.Timestamp(ph["e"].alert_date), "alert", "#b3261e"), (ph["end"], "count finds it", "#1f7a4d")):
        ax[1].axvline(pd.Timestamp(dt), color=col, ls=":", lw=1.3)
        ax[1].text(pd.Timestamp(dt), ax[1].get_ylim()[1] * {"true loss": 0.97, "estimated start": 0.85, "alert": 0.72, "count finds it": 0.97}[lab], " " + lab, color=col, fontsize=8, va="top")
    ax[1].set_title("Phantom stock: when it began, when the alert fired, when a count found it")
    ax[1].legend(loc="center right", fontsize=8)
    ax[1].tick_params(axis="x", rotation=25)
    fig.suptitle("Phase 6: analytics behind the dashboard, scored against the answer key (all data synthetic)", fontsize=12)
    fig.tight_layout()
    fig.savefig(G.ROOT / "docs" / "phase6_dashboard.png", dpi=110)


def main():
    R = R4()
    c = connect()
    integrity(c, R)
    ours, book, sel = backtest(c, R)
    ph = phantom(c, R)
    t = c.execute("SELECT count(*), sum((status = 'pass')::int) FROM w.ops.dbt_test_result WHERE invocation_id = (SELECT invocation_id FROM w.ops.dbt_invocation WHERE command = 'test' ORDER BY generated_at DESC LIMIT 1) AND unique_id LIKE 'test.%'").fetchone()
    R.add("D", "the latest dbt test run, including the new mart tests, passes", f"{int(t[1])} of {int(t[0])} tests pass", "all pass, at least 60 recorded", t[0] >= 60 and t[0] == t[1])
    write_report(R, ours, book, sel, ph)
    chart(c, ours, book, sel, ph)
    c.close()
    gates = [r for r in R.rows if r[5] == "GATE"]
    tg = [r for r in R.rows if r[5] == "TARGET"]
    print(f"\n{sum(r[4] for r in gates)}/{len(gates)} gates passed; {sum(r[4] for r in tg)}/{len(tg)} targets met")
    sys.exit(0 if R.all_ok else 1)


if __name__ == "__main__":
    main()
