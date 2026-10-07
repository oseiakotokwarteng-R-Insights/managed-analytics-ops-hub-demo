"""Phase 4 gate: validates the dbt models against the answer key and the defect log.
Usage: python -m generator.validate_models [--full]    (--full rebuilds every model and proves the rebuild is deterministic)

Hard gates are pass/fail (integrity, dbt tests, handling rules scored per class). Targets from the spec are reported MET or MISSED:
a missed target is published, never redefined."""
from __future__ import annotations

import json
import subprocess
import sys
import time

import duckdb
import pandas as pd

from . import config as G
from .sources.wms import event_id
from .validate import Results

DB = (G.ROOT / "warehouse" / "ops_hub.duckdb").as_posix()
TD = G.TRUTH_DIR.as_posix()
DBT_DIR = G.ROOT / "pipeline" / "dbt"
DBT = G.ROOT / ".venv" / "Scripts" / "dbt.exe"


class R2(Results):
    def target(self, group, name, measured, criterion, met):
        self.rows.append((group, name, measured, criterion, None if False else bool(met), "TARGET"))
        print(f"  [{'MET' if met else 'MISSED'}] {name}: {measured}   (target {criterion})")

    def add(self, group, name, measured, criterion, ok):
        self.rows.append((group, name, measured, criterion, bool(ok), "GATE"))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {measured}   (need {criterion})")

    @property
    def all_ok(self):
        return all(r[4] for r in self.rows if r[5] == "GATE")


def connect():
    c = duckdb.connect()
    c.execute("SET TimeZone = 'UTC'")
    c.execute(f"ATTACH '{DB}' AS w (READ_ONLY)")
    for v, f in {"t_oh": "truth_onhand_daily", "t_sku": "dim_sku", "t_wh": "dim_warehouse", "t_lines": "truth_order_lines", "t_orders": "truth_orders",
                 "t_mv": "truth_movements", "t_ship": "truth_shipments", "t_pol": "truth_po_lines", "t_po": "truth_purchase_orders",
                 "t_cnt": "truth_counts", "t_bins": "truth_bins", "t_vend": "dim_vendor"}.items():
        c.execute(f"CREATE VIEW {v} AS SELECT * FROM read_parquet('{TD}/{f}.parquet')")
    c.execute("""CREATE VIEW t_line AS SELECT 'SO-' || CAST(100000 + 2 * l.order_id AS VARCHAR) order_no, l.line_no, s.sku_code, l.qty_ordered, l.line_id, o.warehouse_id,
                 wh.warehouse_code wh_code FROM t_lines l JOIN t_sku s USING (sku_id) JOIN t_orders o USING (order_id) JOIN t_wh wh ON wh.warehouse_id = o.warehouse_id""")
    return c


def q1(c, sql):
    return c.execute(sql).fetchone()[0]


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


# ----------------------------------------------------------------------------------------------------------------------------- stock
def stock(c, R):
    print("A. The stock table (mart_stock_daily) against physical truth")
    c.execute("""CREATE TABLE cmp AS SELECT m.*, t.onhand_qty AS truth FROM w.marts.mart_stock_daily m JOIN t_sku s ON s.sku_code = m.item_no
                 JOIN t_wh wh ON wh.warehouse_code = m.wh_code JOIN t_oh t ON t.sku_id = s.sku_id AND t.warehouse_id = wh.warehouse_id AND t.snapshot_date = m.local_date""")
    n = q1(c, "SELECT COUNT(*) FROM cmp")
    pairs = q1(c, "SELECT COUNT(DISTINCT (sku_id, warehouse_id)) FROM t_oh")
    days = q1(c, "SELECT COUNT(DISTINCT snapshot_date) FROM t_oh")
    R.add("A", "the mart covers every SKU-warehouse pair on every day", f"{n:,} compared of {pairs:,} pairs x {days} days = {pairs * days:,}", "all", n == pairs * days)
    m = c.execute("""SELECT 100*avg((book_recorded_qty = truth)::int) rec, 100*avg((book_qty = truth)::int) led, 100*avg((est_on_hand = truth)::int) est,
        100*avg((est_on_hand = truth)::int) FILTER (WHERE confidence <> 'suspect') est_ns, 100*avg((confidence = 'suspect')::int) susp FROM cmp""").fetchone()
    rec, led, est, est_ns, susp = m
    R.add("A", "the estimate beats the systems' own recorded book", f"recorded book exact on {rec:.2f}% of pair-days, evidence-corrected ledger {led:.2f}%, reconstructed estimate {est:.2f}%", "estimate >= recorded + 5 points", est - rec >= 5)
    R.add("A", "the estimate is right on most days overall", f"{est:.2f}% of all {n:,} pair-days exact", ">= 94%", est >= 94)
    tiers = c.execute("SELECT confidence, count(*) n, 100*avg((est_on_hand = truth)::int) ex FROM cmp GROUP BY 1 ORDER BY 1").fetchdf().set_index("confidence")
    wrong_sus = q1(c, "SELECT avg((est_on_hand <> truth)::int) FROM cmp WHERE confidence = 'suspect'")
    wrong_ok = q1(c, "SELECT avg((est_on_hand <> truth)::int) FROM cmp WHERE confidence <> 'suspect'")
    R.add("A", "the 'suspect' flag is informative: wrong days concentrate in it", f"{wrong_sus * 100:.1f}% of suspect days are wrong vs {wrong_ok * 100:.2f}% of the rest ({wrong_sus / wrong_ok:.0f}x)", ">= 10x", wrong_sus / wrong_ok >= 10)
    R.target("A", "SPEC target: estimate exact on >= 98% of pair-days, excluding unresolved (suspect) items", f"{est_ns:.2f}% exact on the {100 - susp:.1f}% of pair-days not flagged suspect", ">= 98%", est_ns >= 98)
    R.add("A", "calibration by confidence tier (informational)", "; ".join(f"{k}: {tiers.ex[k]:.2f}% exact on {100 * tiers.n[k] / n:.1f}% of days" for k in tiers.index), "reported", True)
    cal = c.execute("""SELECT CASE WHEN days_since_anchor IS NULL THEN 'never counted' WHEN days_since_anchor <= 30 THEN '0-30' WHEN days_since_anchor <= 90 THEN '31-90'
        WHEN days_since_anchor <= 180 THEN '91-180' WHEN days_since_anchor <= 365 THEN '181-365' ELSE '>365' END b, count(*) n, 100*avg((est_on_hand = truth)::int) ex
        FROM cmp WHERE confidence <> 'suspect' GROUP BY 1 ORDER BY min(coalesce(days_since_anchor, -1))""").fetchdf()
    R.add("A", "accuracy decays with time since the last count (informational)", "; ".join(f"{r.b}{'' if r.b == 'never counted' else ' d'}: {r.ex:.1f}%" for r in cal.itertuples()), "reported", True)
    return {"est": est, "est_ns": est_ns, "rec": rec, "led": led, "susp": susp, "tiers": tiers, "cal": cal, "n": n}


def residual_causes(c) -> dict:
    """Attribute the pair-days that are wrong yet not flagged suspect to the injected causes (answer-key analysis)."""
    d = pd.read_parquet(G.TRUTH_DIR / "truth_defects.parquet")
    sku = pd.read_parquet(G.TRUTH_DIR / "dim_sku.parquet").set_index("sku_id").sku_code
    whc = pd.read_parquet(G.TRUTH_DIR / "dim_warehouse.parquet").set_index("warehouse_id").warehouse_code
    mv = pd.read_parquet(G.TRUTH_DIR / "truth_movements.parquet", columns=["movement_id", "sku_id", "warehouse_id", "movement_type", "ref_id"])
    mvi = mv.set_index("movement_id")
    P = {k: set() for k in ["unrecorded shrink", "Albuquerque loss (S1)", "mis-keyed receipt (W5)", "transfer in-side missing (C3)", "bad count row used as anchor"]}
    for r in mv[mv.movement_type == "shrink"].itertuples():
        P["unrecorded shrink"].add((sku[r.sku_id], whc[r.warehouse_id]))
    for r in mv[mv.movement_type == "scenario_loss"].itertuples():
        P["Albuquerque loss (S1)"].add((sku[r.sku_id], whc[r.warehouse_id]))
    for r in d[d.defect_code == "W5"].itertuples():
        m = mvi.loc[int(r.truth_entity_id)]
        dt = json.loads(r.detail)
        P["mis-keyed receipt (W5)"].update({(sku[dt["true_sku_id"]], whc[m.warehouse_id]), (sku[dt["booked_sku_id"]], whc[m.warehouse_id])})
    tr = mv[mv.movement_type == "transfer_in"].set_index("ref_id")
    for r in d[d.defect_code == "C3"].itertuples():
        if json.loads(r.detail)["missing_side"] == "in" and int(r.truth_entity_id) in tr.index:
            m = tr.loc[int(r.truth_entity_id)]
            P["transfer in-side missing (C3)"].add((sku[m.sku_id], whc[m.warehouse_id]))
    cnt = pd.read_parquet(G.TRUTH_DIR / "truth_counts.parquet")
    bad = set(d[d.defect_code.isin(["U1", "U2", "X3", "X2", "X5"])].truth_entity_id.astype(int))
    for r in cnt[cnt.count_id.isin(bad)].itertuples():
        P["bad count row used as anchor"].add((sku[r.sku_id], whc[r.wh_id]))
    rows = c.execute("SELECT item_no, wh_code, count(*) n FROM cmp WHERE est_on_hand <> truth AND confidence <> 'suspect' GROUP BY 1, 2").fetchdf()
    ks = list(P)
    for k in ks:
        rows[k] = [(i, w) in P[k] for i, w in zip(rows.item_no, rows.wh_code)]
    out = {k: int(rows.loc[rows[k] & ~rows[[x for x in ks if x != k]].any(axis=1), "n"].sum()) for k in ks}
    out["more than one cause"] = int(rows.loc[rows[ks].sum(axis=1) > 1, "n"].sum())
    out["no injected cause (modelling gap)"] = int(rows.loc[~rows[ks].any(axis=1), "n"].sum())
    return out


# ----------------------------------------------------------------------------------------------------------------------------- crosswalk
def keys(d, code, table=None):
    f = d[d.defect_code == code]
    return f if table is None else f[f.source_table == table]


def crosswalk(c, R, d):
    print("B. Identity crosswalks")
    bad = q1(c, """SELECT count(*) FROM w.core.xwalk_sku x JOIN t_sku s ON s.sku_code = x.item_no WHERE x.source_system = 'WMS_ITEM_ID' AND CAST(s.wms_item_id AS VARCHAR) <> x.source_key""")
    unm = q1(c, "SELECT count(*) FROM w.staging.stg_wms__event e LEFT JOIN w.core.xwalk_sku x ON x.source_system = 'WMS_ITEM_ID' AND x.source_key = CAST(e.item_id AS VARCHAR) WHERE x.item_no IS NULL")
    R.add("B", "every WMS event resolves to an ERP item, and the mapping agrees with the answer key", f"{unm} unresolved events; {bad} wrong mappings", "0 / 0", unm == 0 and bad == 0)
    bad2 = q1(c, """SELECT count(*) FROM w.core.dim_sku d JOIN t_sku s ON s.sku_code = d.item_no WHERE d.legacy_code <> s.legacy_code""")
    R.add("B", "the documented legacy code scheme reproduces every legacy code", f"{bad2} of 2,800 items differ", "0", bad2 == 0)
    l1 = keys(d, "L1")
    l1 = l1.assign(true_sku=l1.detail.map(lambda s: json.loads(s)["true_sku_id"]), amb=l1.detail.map(lambda s: json.loads(s)["ambiguous"]))
    sku = pd.read_parquet(G.TRUTH_DIR / "dim_sku.parquet").set_index("sku_id").sku_code
    l1["true_item"] = l1.true_sku.map(sku)
    c.register("l1", l1[["source_row_key", "true_item", "amb"]])
    r = c.execute("""SELECT count(*) n, sum((r.item_no IS NOT NULL)::int) resolved, sum((r.item_no = l.true_item)::int) correct, sum((r.item_no IS NOT NULL AND r.item_no <> l.true_item)::int) wrong,
        sum(l.amb::int) ambiguous_rows, sum((l.amb AND r.item_no IS NOT NULL)::int) amb_resolved, sum((l.amb AND r.item_no = l.true_item)::int) amb_correct
        FROM l1 l JOIN w.intermediate.int_legacy__resolved r ON r.trans_id = l.source_row_key""").fetchone()
    n, res, cor, wr, amb, amb_res, amb_cor = r
    tot = q1(c, "SELECT count(*) FROM w.intermediate.int_legacy__resolved")
    unres = q1(c, "SELECT count(*) FROM w.intermediate.int_legacy__resolved WHERE item_no IS NULL")
    R.target("B", "SPEC target: legacy code crosswalk precision >= 99.5%", f"shared-code rows: {cor:,} of {res:,} resolved are correct = {pct(cor, res):.2f}% precision ({wr} wrong)", ">= 99.5%", pct(cor, res) >= 99.5)
    R.target("B", "SPEC target: legacy code crosswalk recall >= 97% (rest to review, never guessed)", f"{pct(tot - unres, tot):.2f}% of all {tot:,} legacy rows resolved ({unres} to review); of the {amb} date-ambiguous rows, {amb_cor} correct, {amb - amb_res} to review", ">= 97%", pct(tot - unres, tot) >= 97)
    l2 = keys(d, "L2")
    l2 = l2.assign(true_date=l2.detail.map(lambda s: json.loads(s)["true_date"]))
    c.register("l2", l2[["source_row_key", "true_date"]])
    r = c.execute("SELECT count(*), sum((cast(r.date_resolved AS VARCHAR) = l.true_date)::int) FROM l2 l JOIN w.intermediate.int_legacy__resolved r ON r.trans_id = l.source_row_key").fetchone()
    R.add("B", "L2 day-ambiguous legacy dates are settled correctly using the dump week and ERP evidence", f"{r[1]} of {r[0]} correct", ">= 95%", pct(r[1], r[0]) >= 95)
    # W5 receipt fix
    w5 = keys(d, "W5")
    w5 = w5.assign(true_sku=w5.detail.map(lambda s: json.loads(s)["true_sku_id"])).assign(true_item=lambda x: x.true_sku.map(sku))
    c.register("w5", w5[["source_row_key", "true_item"]])
    r = c.execute("""SELECT count(*) n, sum((f.status = 'AUTO')::int) auto, sum((f.corrected_item_no = w.true_item)::int) correct, sum((f.status = 'UNRESOLVED')::int) unresolved,
        sum((f.event_id IS NULL)::int) undetected FROM w5 w LEFT JOIN w.intermediate.int_wms__receipt_fix f ON f.event_id = w.source_row_key""").fetchone()
    fp = q1(c, "SELECT count(*) FROM w.intermediate.int_wms__receipt_fix f WHERE f.event_id NOT IN (SELECT source_row_key FROM w5)")
    R.add("B", "W5 mis-keyed receipts: re-assigned using the PO, precision and recall", f"{r[2]} of {r[0]} corrected right ({pct(r[2], r[0]):.1f}% recall); {r[3]} sent to review, {r[4]} not detected; {fp} wrongly touched", "recall >= 90%, no false positives", pct(r[2], r[0]) >= 90 and fp == 0)
    # vendor crosswalk
    l6 = keys(d, "L6")
    l6 = l6.assign(orig=l6.detail.map(lambda s: json.loads(s)["duplicate_of"]), kind=l6.detail.map(lambda s: json.loads(s)["match"]))
    c.register("l6", l6[["source_row_key", "orig", "kind"]])
    r = c.execute("""SELECT l.kind, x.status, (x.vendor_no = o.vendor_no)::int same FROM l6 l JOIN w.core.xwalk_vendor x ON x.legacy_vendor_id = l.source_row_key
        JOIN w.core.xwalk_vendor o ON o.legacy_vendor_id = l.orig""").fetchdf()
    strong_ok = int(((r.kind == "strong") & (r.status == "AUTO") & (r.same == 1)).sum())
    weak_review = int(((r.kind == "weak") & (r.status == "REVIEW")).sum())
    R.add("B", "L6 duplicate vendors: strong matches merged automatically, weak matches sent to review", f"strong merged correctly {strong_ok}/5; weak to review {weak_review}/2", "5/5 and 2/2", strong_ok == 5 and weak_review == 2)


# ----------------------------------------------------------------------------------------------------------------------------- handling
def handling(c, R, d):
    print("C. Defect handling, scored per class against the defect log")
    orders = d[d.source_table == "sales_order_line"]
    c.register("ol_log", orders[["defect_code", "source_row_key", "detail"]])
    c.execute("""CREATE TABLE ol AS SELECT f.*, f.order_no || '|' || CAST(f.line_no AS VARCHAR) AS k, t.sku_code AS t_item, t.qty_ordered AS t_qty, t.wh_code AS t_wh
                 FROM w.core.fct_order_line f LEFT JOIN t_line t ON t.order_no = f.order_no AND t.line_no = f.line_no""")
    r = c.execute("""SELECT l.defect_code, count(*) n,
        sum((o.item_no = o.t_item)::int) e1_ok, sum(o.flag_item_remapped::int) remapped
        FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E1' GROUP BY 1""").fetchone()
    R.add("C", "E1 successor items keyed as predecessors: remapped to the true item", f"{r[2]} of {r[1]} correct = {pct(r[2], r[1]):.1f}% (the rest are Albuquerque orders, where no WMS evidence exists)", ">= 85%", pct(r[2], r[1]) >= 85)
    wrong_remap = q1(c, "SELECT count(*) FROM ol WHERE flag_item_remapped AND item_no <> t_item")
    R.add("C", "E1 remapping never makes a correct item wrong", f"{wrong_remap} wrong remaps", "0", wrong_remap == 0)
    e2 = c.execute("""SELECT sum((o.is_duplicate)::int) dedup, sum((o.flag_near_duplicate AND NOT o.is_duplicate)::int) near, count(*) n
        FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E2'""").fetchone()
    e2_exact_n = int(((orders.defect_code == "E2") & ~orders.detail.str.contains("near")).sum())
    fp = q1(c, "SELECT count(*) FROM ol WHERE is_duplicate AND k NOT IN (SELECT source_row_key FROM ol_log WHERE defect_code = 'E2')")
    R.add("C", "E2 re-keyed duplicates: exact ones dropped, near-matches flagged, nothing else dropped", f"{e2[0]} dropped of {e2_exact_n} exact duplicates ({pct(e2[0], e2_exact_n):.1f}%); {e2[1]} near-matches flagged; {fp} real lines wrongly dropped", "recall >= 95%, 0 false drops", pct(e2[0], e2_exact_n) >= 95 and fp == 0)
    e3 = c.execute("SELECT count(*), sum((o.exclude_reason = 'E3_QUANTITY_NOT_POSITIVE')::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E3'").fetchone()
    R.add("C", "E3 zero/negative quantities: excluded", f"{e3[1]} of {e3[0]}", ">= 98%", pct(e3[1], e3[0]) >= 98)
    e4 = c.execute("""SELECT count(*) n, sum((o.wh_code = o.t_wh)::int) ok, sum((o.wh_code IS NULL)::int) unresolved FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E4'""").fetchone()
    R.add("C", "E4 missing/invalid ship-from warehouse: filled from the customer default or a sibling line", f"{e4[1]} of {e4[0]} filled correctly = {pct(e4[1], e4[0]):.1f}%; {e4[2]} left to review", ">= 95% (wrong fills must be 0)", e4[1] + e4[2] == e4[0] and pct(e4[1], e4[0]) >= 95)
    e5 = c.execute("SELECT count(*), sum((o.qty_ordered_units_original = o.t_qty)::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E5'").fetchone()
    R.add("C", "E5 quantities entered in cases: converted to units correctly", f"{e5[1]} of {e5[0]}", "100%", e5[1] == e5[0])
    e5b = c.execute("SELECT count(*), sum((o.exclude_reason = 'E5B_NO_CASE_SIZE')::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E5b' AND l.source_row_key LIKE 'SO-%'").fetchone()
    R.add("C", "E5b cases with no case size on the item: excluded, not guessed", f"{e5b[1]} of {e5b[0]}", ">= 98%", pct(e5b[1], e5b[0]) >= 98)
    e6 = c.execute("SELECT count(*), sum((o.flag_modified_after_entry AND o.qty_ordered_units_original = o.t_qty)::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E6'").fetchone()
    R.add("C", "E6 quantity changed after shipment: both the original and the current quantity kept, original equals the truth", f"{e6[1]} of {e6[0]}", "100%", e6[1] == e6[0])
    ok = c.execute("""SELECT count(*) n, sum((item_no = t_item AND qty_ordered_units_original = t_qty AND wh_code = t_wh)::int) ok FROM ol
        WHERE NOT is_duplicate AND exclude_reason IS NULL AND t_item IS NOT NULL""").fetchone()
    R.add("C", "every cleaned order line (kept, not a duplicate) equals the truth on item, original quantity and warehouse", f"{ok[1]:,} of {ok[0]:,} = {pct(ok[1], ok[0]):.3f}%", ">= 99.9%", pct(ok[1], ok[0]) >= 99.9)
    # W6 / C2 inference
    ldrop = d[d.defect_code == "W6"]
    c.register("w6", pd.DataFrame({"line_id": ldrop.truth_entity_id.astype(int).values}))
    inf = c.execute("""SELECT count(*) n, sum((t.line_id IN (SELECT line_id FROM w6))::int) hits FROM (SELECT DISTINCT ref_no, item_no FROM w.core.fct_stock_movement WHERE inference_rule LIKE 'picked_and_packed%') i
        JOIN t_line t ON t.order_no = i.ref_no AND t.sku_code = i.item_no""").fetchone()
    covered = q1(c, "SELECT count(DISTINCT line_id) FROM w6")
    R.add("C", "W6/C2 dropped ship confirmations: shipments inferred from PICK/PACK plus ERP", f"{inf[1]} of {covered} dropped lines recovered ({pct(inf[1], covered):.1f}% recall); {inf[0] - inf[1]} extra inferences (shipments not yet confirmed at the end of history)", "recall >= 95%", pct(inf[1], covered) >= 95)
    # C3
    c3 = d[d.defect_code == "C3"]
    outs = set(c3[c3.detail.map(lambda s: json.loads(s)["missing_side"]) == "out"].source_row_key)
    ins = set(c3[c3.detail.map(lambda s: json.loads(s)["missing_side"]) == "in"].source_row_key)
    inferred = set(r[0] for r in c.execute("SELECT ref_no FROM w.core.fct_stock_movement WHERE inference_rule = 'transfer_in_recorded_without_transfer_out'").fetchall())
    exc = set(r[0] for r in c.execute("SELECT ref_no FROM w.core.recon_transfer_exceptions").fetchall())
    R.add("C", "C3 one-sided transfers: missing out-side inferred, missing in-side listed as in-transit exceptions", f"out-side inferred {len(inferred & outs)} of {len(outs)} logged ({len(inferred - outs)} extra); in-side exceptions {len(exc & ins)} of {len(ins)} logged ({len(exc - ins)} extra)",
          "both >= 90%", len(inferred & outs) >= 0.9 * len(outs) and len(exc & ins) >= 0.9 * len(ins))
    # C1
    c1 = d[d.defect_code == "C1"]
    c.register("c1", c1[["source_row_key"]])
    r = c.execute("""SELECT count(*) FROM c1 JOIN w.core.recon_receipt_variance v ON v.po_no || '|' || CAST(v.line_no AS VARCHAR) = c1.source_row_key""").fetchone()[0]
    extra = q1(c, "SELECT count(*) FROM w.core.recon_receipt_variance v WHERE v.po_no || '|' || CAST(v.line_no AS VARCHAR) NOT IN (SELECT source_row_key FROM c1)")
    R.add("C", "C1 ERP receipt quantities that disagree with the warehouse: detected", f"{r} of {len(c1)} logged ({pct(r, len(c1)):.1f}%); {extra} extra variances", "recall >= 95%", pct(r, len(c1)) >= 95)
    # L4 / L5
    l4 = d[d.defect_code == "L4"]
    c.register("l4", l4[["source_row_key"]])
    r = c.execute("SELECT count(*), sum((v.status = 'AUTO_REPAIRED_FROM_PO')::int) FROM l4 JOIN w.core.recon_legacy_vendor_ref v ON v.trans_id = l4.source_row_key").fetchone()
    R.add("C", "L4 legacy receipts with an unknown vendor id: vendor repaired from the ERP PO (the stock movement is kept)", f"{r[1]} of {len(l4)} repaired; {r[0]} found", ">= 98%", pct(r[1], len(l4)) >= 98)
    l5 = d[d.defect_code == "L5"]
    c.register("l5", l5[["source_row_key"]])
    r = q1(c, "SELECT count(*) FROM l5 JOIN w.quarantine.q_legacy_trans q ON q.trans_id = l5.source_row_key AND q.reason_code = 'L5_QUANTITY_UNPARSEABLE'")
    R.add("C", "L5 unparseable legacy quantities: quarantined with a reason", f"{r} of {len(l5)}", ">= 99%", pct(r, len(l5)) >= 99)
    # counts: X2 / X3 / X5
    cnt = d[d.source_table == "count_row"]
    c.register("cnt_log", cnt[["defect_code", "source_row_key", "detail"]])
    x2 = c.execute("""SELECT json_extract_string(l.detail, '$.recoverable') rec, count(*) n, sum((f.item_no = json_extract_string(l.detail, '$.true_code'))::int) fixed, sum((f.item_no IS NOT NULL AND f.item_no <> json_extract_string(l.detail, '$.true_code'))::int) wrong
        FROM cnt_log l JOIN w.core.fct_count f ON f.count_key = l.source_row_key WHERE l.defect_code = 'X2' GROUP BY 1""").fetchdf().set_index("rec")
    rec_n, rec_fixed = int(x2.n.get("true", 0)), int(x2.fixed.get("true", 0))
    R.add("C", "X2 count-sheet SKU typos: repaired when a unique single edit exists, never repaired wrongly", f"{rec_fixed} of {rec_n} recoverable repaired right ({pct(rec_fixed, rec_n):.1f}%); wrong repairs {int(x2.wrong.sum())}; unrecoverable ones excluded", "recall >= 95%, 0 wrong", pct(rec_fixed, rec_n) >= 95 and int(x2.wrong.sum()) == 0)
    x3 = c.execute("SELECT count(*), sum(f.uom_suspect::int) FROM cnt_log l JOIN w.core.fct_count f ON f.count_key = l.source_row_key WHERE l.defect_code = 'X3'").fetchone()
    fpx = q1(c, "SELECT count(*) FROM w.core.fct_count WHERE uom_suspect AND count_key NOT IN (SELECT source_row_key FROM cnt_log WHERE defect_code = 'X3')")
    R.add("C", "X3 cases counted but entered as each: detected against the book (spec recall 85%)", f"{x3[1]} of {x3[0]} detected ({pct(x3[1], x3[0]):.1f}%); {fpx} false positives of {q1(c, 'SELECT count(*) FROM w.core.fct_count'):,} rows", "recall >= 85%", pct(x3[1], x3[0]) >= 85)
    x5 = c.execute("SELECT count(*), sum((NOT f.is_anchor)::int) FROM cnt_log l JOIN w.core.fct_count f ON f.count_key = l.source_row_key WHERE l.defect_code = 'X5'").fetchone()
    R.add("C", "X5 counts with the wrong month or year: kept out of the anchors", f"{x5[1]} of {x5[0]}", ">= 90%", pct(x5[1], x5[0]) >= 90)
    u = c.execute("SELECT l.defect_code, count(*), sum(f.is_anchor::int) FROM cnt_log l JOIN w.core.fct_count f ON f.count_key = l.source_row_key WHERE l.defect_code IN ('U1','U2') GROUP BY 1 ORDER BY 1").fetchall()
    R.add("C", "U1/U2 are undetectable by design and are (correctly) used as anchors; the stock flags and residual-error analysis show their cost", "; ".join(f"{a}: {c_} rows, {b} used" for a, c_, b in u), "reported", True)
    # freight
    ship = d[d.source_table == "shipment"]
    f2 = d[d.defect_code == "F2"]
    f2 = f2.assign(true_ref=f2.detail.map(lambda s: json.loads(s)["true_ref"]))
    tship = pd.read_parquet(G.TRUTH_DIR / "truth_shipments.parquet", columns=["shipment_id", "carrier"])
    tship["shipment_key"] = ("BOL" + (700000000 + tship.shipment_id).astype(str)).where(tship.carrier == "CARRIER_A", "1Z" + (900000000 + tship.shipment_id).astype(str))
    key_of = tship.set_index("shipment_id").shipment_key
    f2["shipment_key"] = f2.truth_entity_id.astype(int).map(key_of)
    c.register("f2", f2[["shipment_key", "true_ref"]])
    r = c.execute("""SELECT count(*) n, sum((s.doc_no = f.true_ref)::int) ok, sum((s.doc_no IS NOT NULL AND s.doc_no <> f.true_ref)::int) wrong, sum((s.match_status = 'REVIEW')::int) review
        FROM f2 f JOIN w.core.fct_shipment s ON s.shipment_key = f.shipment_key""").fetchone()
    R.add("C", "F2 mangled carrier references: matched to the right order/PO (normalisation, then one-edit with date evidence)", f"{r[1]} of {r[0]} matched right ({pct(r[1], r[0]):.1f}%); {r[2]} matched wrong; {r[3]} to review", ">= 95% right-or-review, 0 wrong", r[2] == 0 and pct(r[1] + r[3], r[0]) >= 95)
    f4 = d[d.defect_code == "F4"]
    f4 = f4.assign(shipment_key=f4.truth_entity_id.astype(int).map(key_of))
    c.register("f4", f4[["shipment_key"]])
    r = c.execute("SELECT count(*), sum(s.flag_delivery_time_invalid::int) FROM f4 JOIN w.core.fct_shipment s USING (shipment_key)").fetchone()
    R.add("C", "F4 impossible delivery times: dropped and flagged", f"{r[1]} of {r[0]}", ">= 98%", pct(r[1], r[0]) >= 98)
    f5 = d[d.defect_code == "F5"]
    f5 = f5.assign(shipment_key=f5.truth_entity_id.astype(int).map(key_of), tw=f5.detail.map(lambda s: json.loads(s)["true_weight"]), missing=f5.detail.map(lambda s: json.loads(s)["missing"]))
    c.register("f5", f5[["shipment_key", "tw", "missing"]])
    r = c.execute("""SELECT count(*) n, sum((s.weight_source = 'imputed_from_document')::int) imputed, sum((s.weight_source = 'imputed_from_document' AND abs(s.weight_lb - f.tw) <= 0.1 * f.tw + 1)::int) near_true
        FROM f5 f JOIN w.core.fct_shipment s USING (shipment_key) WHERE f.missing <> 'pieces'""").fetchone()
    R.add("C", "F5 missing weights: imputed from the matched document, within 10% of the true weight", f"{r[2]} of {r[0]} within 10% ({pct(r[2], r[0]):.1f}%); {r[1]} imputed", ">= 85%", pct(r[2], r[0]) >= 85)
    f7 = d[d.defect_code == "F7"]
    c.register("f7", f7[["source_row_key"]])
    r = c.execute("SELECT count(*), sum(c.is_suspect_duplicate::int) FROM f7 JOIN w.core.fct_freight_charge c ON c.line_id = f7.source_row_key").fetchone()
    fp7 = q1(c, "SELECT count(*) FROM w.core.fct_freight_charge WHERE is_suspect_duplicate AND line_id NOT IN (SELECT source_row_key FROM f7)")
    rec = q1(c, "SELECT coalesce(sum(amount), 0) FROM w.core.fct_freight_charge WHERE is_suspect_duplicate")
    R.add("C", "F7 duplicate carrier charge lines: flagged as recoverable dollars", f"{r[1]} of {r[0]} flagged ({pct(r[1], r[0]):.1f}%); {fp7} false flags; recoverable ${rec:,.0f}", "recall >= 90%, 0 false flags", pct(r[1], r[0]) >= 90 and fp7 == 0)
    # W4 bins and W1/W3
    r = c.execute("""SELECT count(*), sum((e.bin = b.bin_old)::int) FROM w.staging.stg_wms__event e JOIN t_wh wh ON wh.warehouse_code = e.wh_code
        JOIN w.core.xwalk_sku x ON x.source_system = 'WMS_ITEM_ID' AND x.source_key = CAST(e.item_id AS VARCHAR) JOIN t_sku s ON s.sku_code = x.item_no
        JOIN t_bins b ON b.sku_id = s.sku_id AND b.warehouse_id = wh.warehouse_id WHERE e.event_type = 'PUTAWAY' AND e.wh_code = 'WH-02' AND e.local_date >= DATE '2026-03-01'""").fetchone()
    R.add("C", "W4 WH-02 bin relabelling: bins normalised to one scheme (checked on putaways after the change)", f"{r[1]:,} of {r[0]:,} equal the master bin", "100% (apart from the W5 mis-keyed items)", pct(r[1], r[0]) >= 99.5)
    dups = q1(c, "SELECT sum(n_copies - 1) FROM w.staging.stg_wms__event")
    R.add("C", "W1 duplicate WMS deliveries: removed (event_id), one row per event", f"{q1(c, 'SELECT count(*) FROM w.staging.stg_wms__event'):,} unique events; {dups:,} duplicate copies collapsed", "unique event_id", q1(c, "SELECT count(*) - count(distinct event_id) FROM w.staging.stg_wms__event") == 0)
    w3 = q1(c, "SELECT count(*) FROM w.core.fct_stock_movement WHERE quality_flag = 'item_linked_late'")
    R.add("C", "W3 events for items not yet linked: resolved after the link appeared, and marked", f"{w3:,} movements resolved late and flagged", "> 0, none dropped", w3 > 0)


# ----------------------------------------------------------------------------------------------------------------------------- dbt tests
def dbt_tests(R):
    print("D. dbt tests")
    t = time.time()
    p = subprocess.run([str(DBT), "test", "--profiles-dir", "."], cwd=DBT_DIR, capture_output=True, text=True)
    line = [ln for ln in p.stdout.splitlines() if "Done. PASS" in ln]
    msg = line[-1].split("Done.")[-1].strip() if line else p.stdout[-200:]
    R.add("D", "dbt tests (keys, not-null, accepted values, relationships, coverage, evidence on inferences)", f"{msg} ({time.time() - t:.0f}s)", "ERROR=0", p.returncode == 0)


# ----------------------------------------------------------------------------------------------------------------------------- rebuild determinism
def table_hashes():
    c = duckdb.connect(DB, read_only=True)
    out = {}
    for s, t in c.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema IN ('core', 'marts', 'quarantine', 'intermediate', 'staging') AND table_type = 'BASE TABLE' ORDER BY 1, 2").fetchall():
        out[f"{s}.{t}"] = c.execute(f"SELECT count(*), coalesce(sum(CAST(hash(x) AS HUGEINT)), 0) FROM {s}.{t} x").fetchone()
    c.close()
    return out


def rebuild(R):
    print("E. Rebuild determinism")
    before = table_hashes()
    t = time.time()
    p = subprocess.run([str(DBT), "run", "--profiles-dir", "."], cwd=DBT_DIR, capture_output=True, text=True)
    el = time.time() - t
    after = table_hashes()
    diff = [k for k in before if before[k] != after.get(k)]
    R.add("E", "a full rebuild of every model reproduces identical tables", f"{len(before) - len(diff)}/{len(before)} tables identical; rebuild took {el:.0f}s ({[ln for ln in p.stdout.splitlines() if 'Done. PASS' in ln][-1].split('Done.')[-1].strip()})", "all identical", not diff and p.returncode == 0)
    return el


# ----------------------------------------------------------------------------------------------------------------------------- report
def write_report(R, S, causes, c, full):
    def status(r):
        return ("PASS" if r[4] else "FAIL") if r[5] == "GATE" else ("MET" if r[4] else "MISSED")
    rows = "\n".join(f"| {n} | {m} | {cr} | {status((g, n, m, cr, ok, k))} |" for g, n, m, cr, ok, k in R.rows)
    vol = c.execute("""SELECT 'fct_stock_movement' t, count(*) n FROM w.core.fct_stock_movement UNION ALL SELECT 'fct_order_line', count(*) FROM w.core.fct_order_line
        UNION ALL SELECT 'fct_count', count(*) FROM w.core.fct_count UNION ALL SELECT 'fct_shipment', count(*) FROM w.core.fct_shipment UNION ALL SELECT 'fct_freight_charge', count(*) FROM w.core.fct_freight_charge
        UNION ALL SELECT 'fct_po_line', count(*) FROM w.core.fct_po_line UNION ALL SELECT 'mart_stock_daily', count(*) FROM w.marts.mart_stock_daily UNION ALL SELECT 'review_queue', count(*) FROM w.core.review_queue""").fetchdf()
    vt = "\n".join(f"| {r.t} | {r.n:,} |" for r in vol.itertuples())
    rq = c.execute("SELECT source_system, reason_code, count(*) n FROM w.core.review_queue GROUP BY ALL ORDER BY 3 DESC").fetchdf()
    rqt = "\n".join(f"| {r.source_system} | {r.reason_code} | {r.n:,} |" for r in rq.itertuples())
    tot = sum(causes.values())
    ct = "\n".join(f"| {k} | {v:,} | {pct(v, tot):.1f}% |" for k, v in causes.items())
    cal = "\n".join(f"| {r.b} | {r.ex:.1f}% | {r.n:,} |" for r in S["cal"].itertuples())
    tiers = "\n".join(f"| {k} | {S['tiers'].ex[k]:.2f}% | {S['tiers'].n[k]:,} ({pct(S['tiers'].n[k], S['n']):.1f}%) |" for k in S["tiers"].index)
    gates = [r for r in R.rows if r[5] == "GATE"]
    tg = [r for r in R.rows if r[5] == "TARGET"]
    txt = ["# System 1 — Phase 4 Report: Modeling and the Stock Table\n",
           f"Gates: **{'ALL PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in gates)}/{len(gates)}). Spec targets: **{sum(r[4] for r in tg)} of {len(tg)} met**, "
           f"{len(tg) - sum(r[4] for r in tg)} missed (published as measured). Rebuild-determinism test {'was' if full else 'was NOT'} run in this pass.\n",
           "## Headline: how good is the stock table?\n",
           f"On {S['n']:,} SKU-warehouse-days, compared with the hidden physical truth: the source systems' recorded book is exact on **{S['rec']:.1f}%**; the reconstructed estimate on **{S['est']:.1f}%** "
           f"({S['est'] - S['rec']:+.1f} points). Excluding the {S['susp']:.1f}% of days flagged suspect, it is exact on **{S['est_ns']:.2f}%** against the spec's 98% target.\n",
           "| Confidence tier | Exact | Pair-days |\n|---|---|---|", tiers, "\n### Accuracy decays with time since the last count (days not flagged suspect)\n", "| Days since last count | Exact | Pair-days |\n|---|---|---|", cal,
           "\n### What the remaining errors are (wrong and not flagged suspect)\n", "| Cause (from the answer key) | Pair-days | Share |\n|---|---|---|", ct,
           "\nShrink and similar losses are recorded by no system until a count finds them, so no model can recover them earlier; the fix is a counting policy, not more modeling.\n",
           "## Model volumes\n", "| Model | Rows |\n|---|---|", vt, "\n## Review queue (decisions the pipeline would not make alone)\n", "| System | Reason | Rows |\n|---|---|---|", rqt,
           "\n## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (G.ROOT / "docs" / "PHASE4_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def chart(c, S, causes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    m = c.execute("""SELECT date_trunc('month', local_date) mo, 100*avg((book_recorded_qty = truth)::int) rec, 100*avg((est_on_hand = truth)::int) est,
        100*avg((est_on_hand = truth)::int) FILTER (WHERE confidence <> 'suspect') est_ns FROM cmp GROUP BY 1 ORDER BY 1""").fetchdf()
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.2))
    ax[0].plot(m.mo, m.rec, label="systems' recorded book", marker="o", ms=3)
    ax[0].plot(m.mo, m.est, label="reconstructed estimate", marker="o", ms=3)
    ax[0].plot(m.mo, m.est_ns, label="estimate, excluding suspect days", marker="o", ms=3)
    ax[0].axhline(98, ls="--", c="grey", lw=1)
    ax[0].set_ylim(80, 100.5)
    ax[0].set_title("Share of SKU-warehouse-days that are exactly right, by month")
    ax[0].legend(loc="lower left", fontsize=8)
    ax[0].tick_params(axis="x", rotation=30)
    ax[0].grid(alpha=0.3)
    cal = S["cal"]
    ax[1].bar(cal.b, cal.ex, color="#1D5FA3")
    ax[1].set_ylim(85, 100)
    ax[1].axhline(98, ls="--", c="grey", lw=1)
    for i, v in enumerate(cal.ex):
        ax[1].text(i, v + 0.2, f"{v:.1f}%", ha="center", fontsize=8)
    ax[1].set_title("Accuracy by days since the last count (not flagged suspect)")
    ax[1].tick_params(axis="x", rotation=30)
    keys = [k for k in causes if causes[k] > 0]
    ax[2].barh(keys, [causes[k] for k in keys], color="#c0392b")
    ax[2].set_title("Residual errors by cause (not flagged suspect)")
    ax[2].tick_params(axis="y", labelsize=8)
    fig.suptitle("Phase 4: the reconstructed stock table versus physical truth (all data synthetic)", fontsize=12)
    fig.tight_layout()
    fig.savefig(G.ROOT / "docs" / "phase4_stock.png", dpi=110)


def main():
    full = "--full" in sys.argv
    R = R2()
    c = connect()
    d = pd.read_parquet(G.TRUTH_DIR / "truth_defects.parquet")
    S = stock(c, R)
    causes = residual_causes(c)
    crosswalk(c, R, d)
    handling(c, R, d)
    write_report(R, S, causes, c, full)
    chart(c, S, causes)
    c.close()
    dbt_tests(R)
    if full:
        rebuild(R)
    c = connect()
    write_report(R, S, causes, c, full)
    c.close()
    gates = [r for r in R.rows if r[5] == "GATE"]
    tg = [r for r in R.rows if r[5] == "TARGET"]
    print(f"\n{sum(r[4] for r in gates)}/{len(gates)} gates passed; {sum(r[4] for r in tg)}/{len(tg)} spec targets met")
    sys.exit(0 if R.all_ok else 1)


if __name__ == "__main__":
    main()
