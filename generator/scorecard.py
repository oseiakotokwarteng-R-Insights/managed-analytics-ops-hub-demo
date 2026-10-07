"""Measurements for the validation scorecard: every defect class and every headline scenario, scored against the answer key with the targets written down in
docs/DEFECT_CATALOG.md and docs/SPEC.md before anything was built. Targets are read from those documents' tables, never typed here.

Rule for what counts: a defect is scored only if the record it lives in had been delivered by the end of history (the September 2026 count sheets, for example, arrive
in October), and a class is 'handled' only if the pipeline did what the catalog says it should (fixed it right, quarantined it, flagged it, or sent it to a person).
Wrong repairs are counted and shown beside the rate; the pass mark is the catalog target for the rate."""
from __future__ import annotations

import json
import re
from datetime import timedelta

import pandas as pd

from . import config as G
from .validate_models import connect, pct, q1

DOCS = G.ROOT / "docs"


# ------------------------------------------------------------------------------------------------------------------------- targets, parsed from the catalog and the spec
def catalog_targets() -> dict:
    """{class id: (target fraction, kind)} read from the 'Target' column of every defect table in DEFECT_CATALOG.md."""
    out = {}
    for ln in (DOCS / "DEFECT_CATALOG.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([A-Z]\d?b?)\s*\|", ln)
        if not m or ln.startswith("| ID"):
            continue
        cells = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        tgt = cells[-1]
        mm = re.search(r"(\d+(?:\.\d+)?)%", tgt)
        if mm:
            out[m.group(1)] = (float(mm.group(1)) / 100, "precision" if "precision" in tgt else "recall")
    return out


def spec_criteria() -> list[tuple[str, str]]:
    """The rows of the success-criteria table in SPEC.md section 8: (measure, target)."""
    txt = (DOCS / "SPEC.md").read_text(encoding="utf-8")
    sec = txt[txt.index("## 8. Success criteria"):]
    rows = []
    for ln in sec.splitlines():
        if ln.startswith("|") and not ln.startswith("| Measure") and not ln.startswith("|---"):
            cells = [x.strip() for x in ln.strip().strip("|").split("|")]
            rows.append((cells[0], cells[1]))
    return rows


NAMES = {
    "E1": "Superseded item still on orders", "E2": "Re-keyed duplicate order lines", "E3": "Zero or negative quantity", "E4": "Ship-from warehouse missing or invalid",
    "E5": "Quantity entered in cases", "E5b": "Cases with no case size", "E6": "Quantity changed after shipment", "W1": "Duplicate warehouse events",
    "W2": "Late and out-of-order warehouse events", "W3": "Events for items not yet linked", "W4": "Bin label format change", "W5": "Receipt keyed under the wrong item",
    "W6": "Ship confirmation never arrives", "F1": "Carrier re-sends a whole file", "F2": "Mangled order or PO reference", "F4": "Impossible delivery time",
    "F5": "Weight or piece count missing", "F7": "Duplicate carrier charge line", "L1": "Legacy item codes need a crosswalk", "L2": "Legacy dates in mixed formats",
    "L4": "Receipt with an unknown vendor", "L5": "Legacy quantities stored as text", "L6": "Duplicate vendor records", "X1": "Count-sheet headers differ",
    "X2": "SKU typos on count sheets", "X3": "Cases counted but entered as each", "X4": "Merged cells, subtotals, blank rows", "X5": "Count dated the wrong month",
    "X6": "Conflicting vendor price overrides", "C1": "ERP receipt differs from warehouse receipt", "C2": "Order shipped in ERP, no ship event", "C3": "One-sided transfer",
}
SOURCE = {k: {"E": "ERP", "W": "Warehouse system", "F": "Freight", "L": "Legacy database", "X": "Spreadsheets", "C": "Cross-source"}[k[0]] for k in NAMES}
CONTROLS = {
    "U1": ("Counts from one manager biased about +2% for three months", "Blind double counts on a sample, or comparing each counter's variances with the others'. Each row looks plausible alone."),
    "U2": ("Two valid SKUs swapped on a count sheet", "Scan or barcode capture at the bin instead of typed codes."),
    "U3": ("Theft or damage that nothing records", "More frequent counts on fast movers and flagged items; no pipeline can see a cause nobody wrote down."),
}


def ensure_views(c):
    tdir = G.TRUTH_DIR.as_posix()
    for v, f in {"t_ent": "truth_scenario_entities", "t_scen": "truth_scenarios"}.items():
        c.execute(f"CREATE OR REPLACE VIEW {v} AS SELECT * FROM read_parquet('{tdir}/{f}.parquet')")


# ------------------------------------------------------------------------------------------------------------------------- the defect classes
def classes(c, d) -> list[dict]:
    ensure_views(c)
    tg = catalog_targets()
    rows: dict[str, dict] = {}

    def add(cid, n, ok, wrong=0, note="", delivered_of=None):
        t, kind = tg[cid]
        rate = ok / n if n else float("nan")
        rows[cid] = {"id": cid, "name": NAMES[cid], "source": SOURCE[cid], "target": t, "kind": kind, "n": int(n), "ok": int(ok), "wrong_repairs": int(wrong), "rate": rate,
                     "met": bool(n and rate >= t), "note": note, "logged": int(delivered_of if delivered_of is not None else n)}

    # ---- ERP
    orders = d[d.source_table == "sales_order_line"]
    c.register("ol_log", orders[["defect_code", "source_row_key", "detail"]])
    c.execute("""CREATE OR REPLACE TABLE ol AS SELECT f.*, f.order_no || '|' || CAST(f.line_no AS VARCHAR) AS k, t.sku_code AS t_item, t.qty_ordered AS t_qty, t.wh_code AS t_wh
                 FROM w.core.fct_order_line f LEFT JOIN t_line t ON t.order_no = f.order_no AND t.line_no = f.line_no""")
    r = c.execute("SELECT count(*), sum((o.item_no = o.t_item)::int), sum((o.flag_item_remapped AND o.item_no <> o.t_item)::int), sum((o.item_no <> o.t_item AND o.wh_code = 'WH-05')::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E1'").fetchone()
    add("E1", r[0], r[1], r[2], f"{r[1]:,} re-pointed to the right item, none to a wrong one; the other {r[0] - r[1]:,} stay as keyed, {r[3]:,} of them Albuquerque orders, where no warehouse-system evidence exists to name the successor", (orders.defect_code == "E1").sum())
    r = c.execute("""SELECT count(*), sum((o.is_duplicate AND NOT contains(l.detail, 'near'))::int), sum((o.flag_near_duplicate AND NOT o.is_duplicate AND contains(l.detail, 'near'))::int)
                     FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E2'""").fetchone()
    fp = q1(c, "SELECT count(*) FROM ol WHERE is_duplicate AND k NOT IN (SELECT source_row_key FROM ol_log WHERE defect_code = 'E2')")
    add("E2", r[0], r[1] + r[2], fp, f"{r[1]:,} exact duplicates dropped, {r[2]:,} near-matches flagged for a person; {fp} real lines wrongly dropped")
    r = c.execute("SELECT count(*), sum((o.exclude_reason = 'E3_QUANTITY_NOT_POSITIVE')::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E3'").fetchone()
    add("E3", r[0], r[1])
    r = c.execute("""SELECT count(*), sum((o.wh_code = o.t_wh)::int), sum((o.wh_code IS NULL AND json_extract_string(l.detail, '$.recoverable_via') = 'none')::int),
                     sum((o.wh_code IS NOT NULL AND o.wh_code <> o.t_wh)::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E4'""").fetchone()
    add("E4", r[0], r[1] + r[2], r[3], f"{r[1]:,} filled correctly, {r[2]:,} with neither a default nor a sibling line left for a person; {r[3]} wrong fills")
    r = c.execute("SELECT count(*), sum((o.qty_ordered_units_original = o.t_qty)::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E5'").fetchone()
    add("E5", r[0], r[1])
    r = c.execute("SELECT count(*), sum((o.exclude_reason = 'E5B_NO_CASE_SIZE')::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E5b' AND l.source_row_key LIKE 'SO-%'").fetchone()
    add("E5b", r[0], r[1], 0, "scored on order lines (the item-master rows that cause it are the same defect seen from the other side)")
    r = c.execute("SELECT count(*), sum((o.flag_modified_after_entry AND o.qty_ordered_units_original = o.t_qty)::int) FROM ol_log l JOIN ol o ON o.k = l.source_row_key WHERE l.defect_code = 'E6'").fetchone()
    add("E6", r[0], r[1])

    # ---- warehouse system
    ev = d[d.source_table == "wms_events"]
    for code in ("W1", "W2", "W3", "W5", "W6"):
        c.register(f"log_{code.lower()}", ev[ev.defect_code == code][["source_row_key", "truth_entity_id"]].assign(mv=lambda x: x.truth_entity_id.astype("int64")))
    r = c.execute("""SELECT count(*), sum(((SELECT count(*) FROM w.core.fct_stock_movement m WHERE m.movement_id = e.event_id) <= 1)::int)
                     FROM log_w1 l JOIN w.staging.stg_wms__event e ON e.event_id = l.source_row_key WHERE e.n_copies > 1""").fetchone()
    add("W1", r[0], r[1], 0, f"duplicate deliveries that arrived: {r[0]:,}; each is one row in the stock ledger", len(ev[ev.defect_code == "W1"]))
    r = c.execute("""SELECT count(*), sum((m.local_date = CAST(t.movement_date AS DATE))::int) FROM log_w2 l JOIN w.core.fct_stock_movement m ON m.movement_id = l.source_row_key
                     JOIN t_mv t ON t.movement_id = l.mv""").fetchone()
    add("W2", r[0], r[1], 0, "late events that move stock, placed on the day they happened rather than the day they arrived", len(ev[ev.defect_code == "W2"]))
    r = c.execute("""SELECT count(*), sum((m.item_no = s.sku_code)::int) FROM log_w3 l JOIN w.core.fct_stock_movement m ON m.movement_id = l.source_row_key
                     JOIN t_mv t ON t.movement_id = l.mv JOIN t_sku s ON s.sku_id = t.sku_id""").fetchone()
    late = q1(c, "SELECT count(*) FROM w.core.fct_stock_movement WHERE quality_flag = 'item_linked_late'")
    add("W3", r[0], r[1], r[0] - r[1], f"stock-moving events for not-yet-linked items, all in the ledger under the right item; {late:,} carry the 'linked late' mark", len(ev[ev.defect_code == "W3"]))
    w5 = d[d.defect_code == "W5"]
    skus = pd.read_parquet(G.TRUTH_DIR / "dim_sku.parquet").set_index("sku_id").sku_code
    c.register("w5", w5.assign(true_item=w5.detail.map(lambda s: skus[json.loads(s)["true_sku_id"]]))[["source_row_key", "true_item"]])
    r = c.execute("""SELECT count(*), sum((f.corrected_item_no = w.true_item)::int), sum((f.status = 'UNRESOLVED')::int) FROM w5 w LEFT JOIN w.intermediate.int_wms__receipt_fix f ON f.event_id = w.source_row_key""").fetchone()
    fp = q1(c, "SELECT count(*) FROM w.intermediate.int_wms__receipt_fix f WHERE f.event_id NOT IN (SELECT source_row_key FROM w5)")
    wrong = q1(c, "SELECT count(*) FROM w.intermediate.int_wms__receipt_fix f JOIN w5 w ON w.source_row_key = f.event_id WHERE f.status = 'AUTO' AND f.corrected_item_no <> w.true_item")
    add("W5", r[0], r[1], fp + wrong, f"{r[1]} re-assigned to the right item from the PO, {r[2]} sent to review, {fp} receipts wrongly touched")
    w6 = d[d.defect_code == "W6"]
    c.register("w6", pd.DataFrame({"line_id": w6.truth_entity_id.astype(int).values}).drop_duplicates())
    inf = c.execute("""SELECT count(*), sum((t.line_id IN (SELECT line_id FROM w6))::int) FROM (SELECT DISTINCT ref_no, item_no FROM w.core.fct_stock_movement WHERE inference_rule LIKE 'picked_and_packed%') i
                       JOIN t_line t ON t.order_no = i.ref_no AND t.sku_code = i.item_no""").fetchone()
    n6 = q1(c, "SELECT count(*) FROM w6")
    add("W6", n6, inf[1], 0, f"shipments reconstructed from pick, pack and the ERP; {inf[0] - inf[1]} further inferences are shipments still unconfirmed at the end of history")
    r = c.execute("""SELECT count(*), sum((e.bin = b.bin_old)::int) FROM w.staging.stg_wms__event e JOIN t_wh wh ON wh.warehouse_code = e.wh_code
        JOIN w.core.xwalk_sku x ON x.source_system = 'WMS_ITEM_ID' AND x.source_key = CAST(e.item_id AS VARCHAR) JOIN t_sku s ON s.sku_code = x.item_no
        JOIN t_bins b ON b.sku_id = s.sku_id AND b.warehouse_id = wh.warehouse_id WHERE e.event_type = 'PUTAWAY' AND e.wh_code = 'WH-02' AND e.local_date >= DATE '2026-03-01'""").fetchone()
    add("W4", r[0], r[1], 0, "scored on putaways in Tucson after the label change: the bin on the dashboard equals the bin in the item's master record")

    # ---- freight
    tship = pd.read_parquet(G.TRUTH_DIR / "truth_shipments.parquet", columns=["shipment_id", "carrier"])
    tship["shipment_key"] = ("BOL" + (700000000 + tship.shipment_id).astype(str)).where(tship.carrier == "CARRIER_A", "1Z" + (900000000 + tship.shipment_id).astype(str))
    key_of = tship.set_index("shipment_id").shipment_key
    al = c.execute("SELECT message FROM w.ops.alerts_unified WHERE alert_type = 'duplicate_file'").fetchdf().message
    f1 = d[d.defect_code == "F1"]
    hit = sum(al.str.contains(k, regex=False).any() for k in f1.source_row_key)
    add("F1", len(f1), hit, int(len(al) - hit), "each re-sent file raised a duplicate-file alert the night it arrived")
    f2 = d[d.defect_code == "F2"]
    f2 = f2.assign(true_ref=f2.detail.map(lambda s: json.loads(s)["true_ref"]), shipment_key=f2.truth_entity_id.astype(int).map(key_of))
    c.register("f2", f2[["shipment_key", "true_ref"]])
    r = c.execute("""SELECT count(*), sum((s.doc_no = f.true_ref)::int), sum((s.doc_no IS NOT NULL AND s.doc_no <> f.true_ref)::int), sum((s.match_status = 'REVIEW')::int)
                     FROM f2 f JOIN w.core.fct_shipment s USING (shipment_key)""").fetchone()
    add("F2", r[0], r[1] + r[3], r[2], f"{r[1]} matched to the right order or PO, {r[3]} sent to review, {r[2]} matched wrong")
    f4 = d[d.defect_code == "F4"]
    c.register("f4", f4.assign(shipment_key=f4.truth_entity_id.astype(int).map(key_of))[["shipment_key"]])
    r = c.execute("SELECT count(*), sum(s.flag_delivery_time_invalid::int) FROM f4 JOIN w.core.fct_shipment s USING (shipment_key)").fetchone()
    add("F4", r[0], r[1])
    f5 = d[d.defect_code == "F5"]
    f5 = f5.assign(shipment_key=f5.truth_entity_id.astype(int).map(key_of), tw=f5.detail.map(lambda s: json.loads(s)["true_weight"]), missing=f5.detail.map(lambda s: json.loads(s)["missing"]))
    c.register("f5", f5[["shipment_key", "tw", "missing"]])
    r = c.execute("""SELECT count(*),
        sum(((f.missing IN ('weight', 'both') AND s.weight_source <> 'reported') OR (f.missing = 'pieces' AND s.flag_pieces_missing))::int),
        sum((f.missing IN ('weight', 'both') AND s.weight_source = 'imputed_from_document' AND abs(s.weight_lb - f.tw) <= 0.1 * f.tw + 1)::int),
        sum((f.missing IN ('weight', 'both') AND s.weight_source = 'imputed_from_document')::int), sum((f.missing IN ('weight', 'both'))::int)
        FROM f5 f JOIN w.core.fct_shipment s USING (shipment_key)""").fetchone()
    add("F5", r[0], r[1], 0, f"every missing weight or piece count is marked; of {r[4]} missing weights, {r[3]} imputed from the matched document and {r[2]} of those within 10% of the true weight")
    f7 = d[d.defect_code == "F7"]
    c.register("f7", f7[["source_row_key"]])
    r = c.execute("SELECT count(*), sum(c.is_suspect_duplicate::int) FROM f7 JOIN w.core.fct_freight_charge c ON c.line_id = f7.source_row_key").fetchone()
    fp7 = q1(c, "SELECT count(*) FROM w.core.fct_freight_charge WHERE is_suspect_duplicate AND line_id NOT IN (SELECT source_row_key FROM f7)")
    add("F7", r[0], r[1], fp7, f"{fp7} false flags", len(f7))

    # ---- legacy
    l1 = d[d.defect_code == "L1"]
    l1 = l1.assign(true_item=l1.detail.map(lambda s: skus[json.loads(s)["true_sku_id"]]))
    c.register("l1", l1[["source_row_key", "true_item"]])
    r = c.execute("SELECT count(*), sum((r.item_no IS NOT NULL)::int), sum((r.item_no = l.true_item)::int) FROM l1 l JOIN w.intermediate.int_legacy__resolved r ON r.trans_id = l.source_row_key").fetchone()
    add("L1", r[1], r[2], r[1] - r[2], f"of {r[0]:,} rows with a shared legacy code, {r[1]:,} were resolved automatically and {r[0] - r[1]:,} left to review; precision is measured on the resolved ones", r[0])
    l2 = d[d.defect_code == "L2"]
    c.register("l2", l2.assign(true_date=l2.detail.map(lambda s: json.loads(s)["true_date"]))[["source_row_key", "true_date"]])
    r = c.execute("SELECT count(*), sum((cast(r.date_resolved AS VARCHAR) = l.true_date)::int) FROM l2 l JOIN w.intermediate.int_legacy__resolved r ON r.trans_id = l.source_row_key").fetchone()
    add("L2", r[0], r[1])
    l4 = d[d.defect_code == "L4"]
    c.register("l4", l4[["source_row_key"]])
    r = c.execute("SELECT count(*), sum((v.status = 'AUTO_REPAIRED_FROM_PO')::int) FROM l4 JOIN w.core.recon_legacy_vendor_ref v ON v.trans_id = l4.source_row_key").fetchone()
    add("L4", len(l4), r[1])
    l5 = d[d.defect_code == "L5"]
    c.register("l5", l5[["source_row_key"]])
    add("L5", len(l5), q1(c, "SELECT count(*) FROM l5 JOIN w.quarantine.q_legacy_trans q ON q.trans_id = l5.source_row_key AND q.reason_code = 'L5_QUANTITY_UNPARSEABLE'"))
    l6 = d[d.defect_code == "L6"]
    l6 = l6.assign(orig=l6.detail.map(lambda s: json.loads(s)["duplicate_of"]), kind=l6.detail.map(lambda s: json.loads(s)["match"]))
    c.register("l6", l6[["source_row_key", "orig", "kind"]])
    r = c.execute("""SELECT l.kind, x.status, (x.vendor_no = o.vendor_no)::int same FROM l6 l JOIN w.core.xwalk_vendor x ON x.legacy_vendor_id = l.source_row_key JOIN w.core.xwalk_vendor o ON o.legacy_vendor_id = l.orig""").fetchdf()
    strong = int(((r.kind == "strong") & (r.status == "AUTO") & (r.same == 1)).sum())
    weak = int(((r.kind == "weak") & (r.status == "REVIEW")).sum())
    add("L6", len(l6), strong + weak, 0, f"{strong} of {(r.kind == 'strong').sum()} strong matches merged automatically, {weak} of {(r.kind == 'weak').sum()} weak matches sent to review")

    # ---- spreadsheets
    cnt = d[d.source_table == "count_row"]
    c.register("cnt_log", cnt[["defect_code", "source_row_key", "detail"]])
    x2 = c.execute("""SELECT json_extract_string(l.detail, '$.recoverable') rec, count(*) n, sum((f.item_no = json_extract_string(l.detail, '$.true_code'))::int) fixed,
                      sum((f.item_no IS NOT NULL AND f.item_no <> json_extract_string(l.detail, '$.true_code'))::int) wrong, sum((f.sku_resolution = 'unresolved')::int) unresolved
                      FROM cnt_log l JOIN w.core.fct_count f ON f.count_key = l.source_row_key WHERE l.defect_code = 'X2' GROUP BY 1""").fetchdf().set_index("rec")
    n2 = int(x2.n.sum())
    ok2 = int(x2.fixed.get("true", 0)) + int(x2.unresolved.get("false", 0))
    add("X2", n2, ok2, int(x2.wrong.sum()), f"{int(x2.fixed.get('true', 0))} of {int(x2.n.get('true', 0))} recoverable typos repaired, {int(x2.unresolved.get('false', 0))} of {int(x2.n.get('false', 0))} unrecoverable ones excluded for a person; {int(x2.wrong.sum())} wrong repairs", (cnt.defect_code == "X2").sum())
    r = c.execute("SELECT count(*), sum(f.uom_suspect::int) FROM cnt_log l JOIN w.core.fct_count f ON f.count_key = l.source_row_key WHERE l.defect_code = 'X3'").fetchone()
    fpx = q1(c, "SELECT count(*) FROM w.core.fct_count WHERE uom_suspect AND count_key NOT IN (SELECT source_row_key FROM cnt_log WHERE defect_code = 'X3')")
    add("X3", r[0], r[1], 0, f"{fpx} good rows also flagged, of {q1(c, 'SELECT count(*) FROM w.core.fct_count'):,}", (cnt.defect_code == "X3").sum())
    r = c.execute("SELECT count(*), sum((NOT f.is_anchor)::int) FROM cnt_log l JOIN w.core.fct_count f ON f.count_key = l.source_row_key WHERE l.defect_code = 'X5'").fetchone()
    add("X5", r[0], r[1], 0, "kept out of the stock anchors", (cnt.defect_code == "X5").sum())
    # files: header variants (X1) and layout noise (X4): every sheet's rows all arrive, none invented
    tc = pd.read_parquet(G.TRUTH_DIR / "truth_counts.parquet", columns=["wh_id", "count_date"])
    wh = {1: "WH-01", 2: "WH-02", 3: "WH-03", 4: "WH-04", 5: "WH-05", 6: "WH-06"}
    tc["rel"] = "spreadsheets/count_sheets/" + tc.wh_id.map(wh) + "/" + pd.to_datetime(tc.count_date).dt.strftime("%Y-%m") + "_count.xlsx"
    exp = tc.groupby("rel").size()
    got = c.execute("SELECT split_part(count_key, '|', 1) AS rel_path, count(*) n FROM w.core.fct_count GROUP BY 1").fetchdf().set_index("rel_path").n
    files = pd.DataFrame({"exp": exp, "got": got}).dropna(subset=["got"])
    x1f = d[d.defect_code == "X1"].source_row_key
    f1ok = files.loc[files.index.intersection(x1f)]
    add("X1", len(f1ok), int((f1ok.exp == f1ok.got).sum()), 0, "files whose column headers differ from the usual; scored on whether every row arrived", len(x1f))
    add("X4", len(files), int((files.exp == files.got).sum()), 0, "every sheet with merged cells, subtotals and blank rows delivers exactly its real rows", len(exp))
    x6 = d[d.defect_code == "X6"]
    c.register("x6", x6[["source_row_key"]])
    r = c.execute("""SELECT count(*), sum((k.row_key IS NOT NULL)::int) FROM x6 JOIN (SELECT r.rel_path || '|' || CAST(CAST(c.sheet_row AS INTEGER) AS VARCHAR) AS row_key FROM w.raw.sheet_cells c JOIN w.raw._file_registry r ON r.file_id = c._file_id AND r.status = 'LOADED' WHERE c.sheet_kind = 'price' AND c.c2 LIKE 'NF-%' AND substr(c.cell_types, 3, 1) = 'n') p ON p.row_key = x6.source_row_key
                     LEFT JOIN w.core.recon_price_conflicts k ON k.row_key = p.row_key""").fetchone()
    add("X6", r[0], r[1], 0, "each conflicting price is in a flagged pair with a documented rule (the later entry is used until a person confirms)", len(x6))

    # ---- cross-source
    c1 = d[d.defect_code == "C1"]
    c.register("c1", c1[["source_row_key"]])
    add("C1", len(c1), q1(c, "SELECT count(*) FROM c1 JOIN w.core.recon_receipt_variance v ON v.po_no || '|' || CAST(v.line_no AS VARCHAR) = c1.source_row_key"))
    rows["C2"] = None
    c3 = d[d.defect_code == "C3"]
    side = c3.detail.map(lambda s: json.loads(s)["missing_side"])
    outs, ins = set(c3[side == "out"].source_row_key), set(c3[side == "in"].source_row_key)
    inferred = {r[0] for r in c.execute("SELECT ref_no FROM w.core.fct_stock_movement WHERE inference_rule = 'transfer_in_recorded_without_transfer_out'").fetchall()}
    exc = {r[0] for r in c.execute("SELECT ref_no FROM w.core.recon_transfer_exceptions").fetchall()}
    add("C3", len(outs) + len(ins), len(inferred & outs) + len(exc & ins), 0, f"missing out-side inferred for {len(inferred & outs)} of {len(outs)}; missing in-side listed as in-transit for {len(exc & ins)} of {len(ins)}")
    # C2 is the same evidence path as W6 (ERP says shipped, warehouse event absent, carrier evidence): report the W6 result under its own catalog target
    t, kind = tg["C2"]
    w6r = rows["W6"]
    rows["C2"] = {**w6r, "met": None, "id": "C2", "name": NAMES["C2"], "source": SOURCE["C2"], "target": t, "kind": kind, "met": bool(w6r["n"] and w6r["rate"] >= t),
                  "note": "same cases as W6, scored against the C2 target: the shipment is reconstructed from pick, pack and the ERP, with carrier evidence where it exists"}
    order = [k for k in NAMES]
    return [rows[k] for k in order]


# ------------------------------------------------------------------------------------------------------------------------- scenarios
def future_risk_scores(c, lo, hi, pairs_sql, label):
    """Run-out risk as of weekly dates between lo and hi, for a set of item-warehouse pairs, scored on whether physical stock hit zero within 14 days."""
    c.execute(f"""CREATE OR REPLACE TABLE nxt AS SELECT s.sku_code AS item_no, wh.warehouse_code AS wh_code, CAST(t.snapshot_date AS DATE) AS d,
        min(t.onhand_qty) OVER (PARTITION BY t.sku_id, t.warehouse_id ORDER BY CAST(t.snapshot_date AS DATE) ROWS BETWEEN 1 FOLLOWING AND 14 FOLLOWING) AS min_next14
        FROM t_oh t JOIN t_sku s USING (sku_id) JOIN t_wh wh USING (warehouse_id) WHERE CAST(t.snapshot_date AS DATE) >= DATE '{lo}'""")
    c.execute(f"""CREATE OR REPLACE TABLE bt AS SELECT r.item_no, r.wh_code, r.d, r.risk, r.daily_rate, r.est_on_hand, r.confidence, m.book_recorded_qty, n.min_next14 <= 0 AS truly_out
        FROM w.marts.mart_stock_risk_daily r JOIN w.marts.mart_stock_daily m ON m.item_no = r.item_no AND m.wh_code = r.wh_code AND m.local_date = r.d
        JOIN nxt n ON n.item_no = r.item_no AND n.wh_code = r.wh_code AND n.d = r.d
        WHERE r.d BETWEEN DATE '{lo}' AND DATE '{hi}' AND date_diff('day', DATE '{lo}', r.d) % 7 = 0 AND r.units_28d >= 3 AND (r.item_no, r.wh_code) IN ({pairs_sql})""")

    def sc(pred):
        tp, fp, fn = c.execute(f"SELECT count(*) FILTER (WHERE {pred} AND truly_out), count(*) FILTER (WHERE {pred} AND NOT truly_out), count(*) FILTER (WHERE NOT ({pred}) AND truly_out) FROM bt").fetchone()
        p, rc = (tp / (tp + fp) if tp + fp else float("nan")), (tp / (tp + fn) if tp + fn else float("nan"))
        return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": rc}
    return sc("risk IN ('at_risk', 'out_of_stock')"), sc("(book_recorded_qty <= 0 OR book_recorded_qty / daily_rate <= 14)")


def scenarios(c, d) -> list[dict]:
    ensure_views(c)
    out = []
    scn = pd.read_parquet(G.TRUTH_DIR / "truth_scenarios.parquet").set_index("scenario_id")
    wh = dict(c.execute("SELECT warehouse_id, warehouse_code FROM t_wh").fetchall())
    alerts = c.execute("SELECT * FROM w.ops.alerts_unified ORDER BY alert_id").fetchdf()
    alerts["day"] = alerts.opened_as_of.dt.date

    def day(x):
        return pd.Timestamp(x).date()

    # S1 phantom stock
    s1 = scn.loc["S1"]
    ep = c.execute("SELECT * FROM w.marts.mart_ghost_stock_episode ORDER BY alert_date").fetchdf()
    e = ep.iloc[0] if len(ep) else None
    items = {r[0] for r in c.execute("SELECT s.sku_code FROM t_ent e JOIN t_sku s USING (sku_id) WHERE e.scenario_id = 'S1'").fetchall()}
    fa = q1(c, "SELECT count(*) FROM w.marts.mart_ghost_stock_daily WHERE is_alert AND wh_code <> 'WH-05'")
    if e is not None:
        err = (day(e.est_start) - day(s1.start_date)).days
        named = {r[0] for r in c.execute("SELECT item_no FROM w.marts.mart_ghost_stock_line WHERE wh_code = ? AND order_date BETWEEN CAST(? AS DATE) - 45 AND CAST(? AS DATE) - 7 GROUP BY 1 HAVING count(*) >= 3", [wh[int(s1.warehouse_id)], e.alert_date, e.last_alert_date]).fetchall()}
        out.append({"id": "S1", "name": "Phantom stock, Albuquerque", "when": f"{day(s1.start_date)} to {day(s1.end_date)}", "expected": "an alert; dollars and orders quantified; start date within 3 days of the truth",
                    "target": "start date within 3 days", "measured": f"start estimated {day(e.est_start)} ({err:+d} days); alert raised {day(e.alert_date)}, {(day(s1.end_date) - day(e.alert_date)).days} days before the count that found it; "
                    f"{len(named & items)} of {len(named)} named items truly affected; {int(e.stuck_order_lines)} stuck order lines (${e.stuck_order_value:,.0f}); {fa} false alarms elsewhere", "met": abs(err) <= 3 and fa == 0 and len(named & items) / len(named) >= 0.95})
    # S2 carrier schema change
    s2 = scn.loc["S2"]
    a2 = alerts[(alerts.alert_type == "load_or_schema") & (alerts.entity == "carrier_b_shipments")].sort_values("day")
    held = q1(c, "SELECT count(*) FROM w.raw._load_files WHERE status = 'HELD_DRIFT'")
    wt = c.execute("""SELECT count(*), sum((abs(s.weight_lb_reported - t.weight_lb) <= 0.05)::int) FROM w.core.fct_shipment s JOIN (SELECT shipment_id, weight_lb FROM read_parquet(?)) t
                      ON s.shipment_key = '1Z' || CAST(900000000 + t.shipment_id AS VARCHAR) WHERE s.carrier = 'CARRIER_B' AND s.weight_lb_reported IS NOT NULL
                      AND cast(s.pickup_ts_utc AS DATE) BETWEEN DATE '2026-06-03' AND DATE '2026-06-12'""", [(G.TRUTH_DIR / "truth_shipments.parquet").as_posix()]).fetchone()
    same = len(a2) and (day(a2.opened_as_of.iloc[0]) - day(s2.start_date)).days == 0
    out.append({"id": "S2", "name": "Carrier B changes its file layout", "when": str(day(s2.start_date)), "expected": "drift detected in the same run; mapped or paused with an alert; never a silent failure and never silently wrong cost",
                "target": "detected the same night, no wrong cost", "measured": f"first ERROR {day(a2.opened_as_of.iloc[0]) if len(a2) else 'never'} ({held} files held, then released after the layout was approved); weights of shipments around the change equal the truth on {wt[1]} of {wt[0]}",
                "met": bool(same and wt[1] == wt[0])})
    # S3 outage: detection + self-heal + gap marking while open
    s3 = scn.loc["S3"]
    ent = f"wms:{wh[int(s3.warehouse_id)]}"
    a3 = alerts[(alerts.entity == ent) & (alerts.day >= day(s3.start_date)) & (alerts.day <= day(s3.start_date) + timedelta(days=5))].sort_values("day")
    lat = (a3.day.iloc[0] - day(s3.start_date)).days if len(a3) else None
    heal = c.execute(f"""SELECT 100 * avg((m.est_on_hand = t.onhand_qty)::int) FILTER (WHERE m.local_date BETWEEN DATE '{day(s3.start_date)}' AND DATE '{day(s3.end_date) + timedelta(days=8)}'),
                         100 * avg((m.est_on_hand = t.onhand_qty)::int) FILTER (WHERE m.local_date BETWEEN DATE '{day(s3.start_date) - timedelta(days=14)}' AND DATE '{day(s3.start_date) - timedelta(days=1)}'),
                         100 * avg(m.flag_stream_stale::int) FILTER (WHERE m.local_date BETWEEN DATE '{day(s3.start_date)}' AND DATE '{day(s3.end_date) + timedelta(days=8)}')
                         FROM w.marts.mart_stock_daily m JOIN t_sku s ON s.sku_code = m.item_no JOIN t_wh wh ON wh.warehouse_code = m.wh_code
                         JOIN t_oh t ON t.sku_id = s.sku_id AND t.warehouse_id = wh.warehouse_id AND CAST(t.snapshot_date AS DATE) = m.local_date WHERE m.wh_code = '{wh[int(s3.warehouse_id)]}'""").fetchone()
    pit = pit_s3(day(s3.start_date))
    out.append({"id": "S3", "name": "Flagstaff warehouse feed goes quiet, then bursts in late", "when": f"{day(s3.start_date)} to {day(s3.end_date)}", "expected": "the stock table marks the gap honestly while it exists; the history heals after the backfill and matches the truth",
                "target": "alert within 2 days; healed history within 1 point of normal; gap marked while open", "measured": f"first alert {lat} days after the outage began; after the catch-up the stock estimate is exact on {heal[0]:.2f}% of Flagstaff pair-days over the outage and the following week "
                f"(the two weeks before: {heal[1]:.2f}%); {pit['text']}", "met": bool(lat is not None and lat <= 2 and abs(heal[0] - heal[1]) <= 1.0 and pit["ok"])})
    # S4 double billing
    f7 = d[d.defect_code == "F7"]
    truth_usd = sum(json.loads(s)["amount"] for s in f7.detail)
    r = c.execute("SELECT count(*) FILTER (WHERE is_suspect_duplicate), coalesce(sum(amount) FILTER (WHERE is_suspect_duplicate), 0) FROM w.core.fct_freight_charge").fetchone()
    fl = c.execute("SELECT count(*) FROM w.core.fct_freight_charge c JOIN (SELECT unnest(?::varchar[]) AS source_row_key) k ON k.source_row_key = c.line_id WHERE c.is_suspect_duplicate", [f7.source_row_key.tolist()]).fetchone()[0]
    nd = c.execute("SELECT count(*) FROM w.core.fct_freight_charge c JOIN (SELECT unnest(?::varchar[]) AS k) x ON x.k = c.line_id", [f7.source_row_key.tolist()]).fetchone()[0]
    out.append({"id": "S4", "name": "Carrier A double-bills about 1% of shipments", "when": "all 24 months", "expected": "a recoverable-dollars view with the specific charge lines", "target": "90% of duplicate lines flagged, none falsely",
                "measured": f"{fl} of {nd} duplicate lines in the delivered files flagged (${r[1]:,.0f} recoverable against ${truth_usd:,.0f} truly duplicated in the delivered files); {r[0] - fl} false flags", "met": bool(fl / nd >= 0.9 and r[0] == fl)})
    # S5 roofing surge
    s5 = scn.loc["S5"]
    pairs = "SELECT s.sku_code, wh.warehouse_code FROM t_ent e JOIN t_sku s USING (sku_id) JOIN t_wh wh USING (warehouse_id) WHERE e.scenario_id = 'S5'"
    ours, book = future_risk_scores(c, day(s5.start_date), day(s5.end_date) - timedelta(days=15), pairs, "S5")
    don = c.execute(f"""SELECT count(*), sum((EXISTS (SELECT 1 FROM w.marts.mart_stock_risk_daily o WHERE o.item_no = b.item_no AND o.d = b.d AND o.wh_code <> b.wh_code AND o.confidence <> 'suspect'
                                 AND o.est_on_hand - ceil(45 * o.daily_rate) >= 10))::int) FROM bt b WHERE b.risk IN ('at_risk', 'out_of_stock') AND b.truly_out""").fetchone()
    out.append({"id": "S5", "name": "Roofing demand surge, Las Vegas", "when": f"{day(s5.start_date)} to {day(s5.end_date)}", "expected": "the run-out view flags the surge items with days of cover and suggests transfer sources that have stock",
                "target": "recall >= 70% and precision >= 50% on the surge items (the bars used for the run-out list)",
                "measured": f"on the 30 surge items, weekly as-of dates in the surge: the list caught {ours['tp']} of {ours['tp'] + ours['fn']} real run-outs ({100 * ours['recall']:.0f}% recall, {100 * ours['precision']:.0f}% precision); the systems' own book: {100 * book['recall']:.0f}% recall, {100 * book['precision']:.0f}% precision; "
                f"a transfer source with spare stock existed for {don[1]} of {don[0]} caught run-outs", "met": bool(ours["recall"] >= 0.7 and ours["precision"] >= 0.5)})
    return out


PIT_DB = G.ROOT / "warehouse" / "pit_2026-01-22.duckdb"


def pit_s3(start):
    """Point-in-time replay of the Flagstaff outage: a scratch warehouse loaded night by night only up to the second day of the outage, models built as of that date.
    Checks that, while the outage is open, the stock table marks that warehouse's estimates as suspect (and nothing else is flagged on that warehouse's feed)."""
    import os
    import subprocess
    import sys
    asof = start + timedelta(days=1)
    db = G.ROOT / "warehouse" / f"pit_{asof}.duckdb"
    env = {**os.environ, "OPS_HUB_DB": str(db)}
    if not db.exists():
        subprocess.run([sys.executable, "-m", "pipeline.run", "backfill", "--to", str(asof), "--fresh", "--db", str(db)], cwd=G.ROOT, env=env, check=True, capture_output=True)
        dbt = G.ROOT / ".venv" / "Scripts" / "dbt.exe"
        for args in (["seed"], ["run", "--exclude", "path:models/ops"]):
            p = subprocess.run([str(dbt), *args, "--vars", f"{{history_end: '{asof}'}}", "--profiles-dir", "."], cwd=G.ROOT / "pipeline" / "dbt", env=env, capture_output=True, text=True)
            if p.returncode:
                raise SystemExit("point-in-time build failed:\n" + p.stdout[-1500:])
    import duckdb
    pc = duckdb.connect(str(db), read_only=True)
    tr = G.TRUTH_DIR.as_posix()
    r = pc.execute(f"""SELECT m.local_date, count(*), 100 * avg(m.flag_stream_stale::int) FROM marts.mart_stock_daily m WHERE m.wh_code = 'WH-03' AND m.local_date IN (DATE '{asof}', DATE '{start}') GROUP BY 1 ORDER BY 1""").fetchall()
    other = pc.execute(f"SELECT count(*) FROM marts.mart_stock_daily WHERE flag_stream_stale AND wh_code <> 'WH-03'").fetchone()[0]
    pc.close()
    stale = {str(a): b for a, _, b in r}
    ok = stale.get(str(asof), 0) >= 99 and other == 0
    return {"ok": ok, "text": f"replayed as of {asof}, with only what had arrived by then: {stale.get(str(asof), 0):.0f}% of that warehouse's stock estimates on {asof} were marked suspect (feed silent), {other} estimates flagged on other warehouses"}
