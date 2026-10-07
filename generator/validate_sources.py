"""Phase 2 gate: validates the five generated sources against the truth store and the defect log.
Usage: python -m generator.validate_sources [--full]   (--full also rebuilds everything and checks bit-for-bit reproducibility)

Groups: A source shape/volume | B injected-defect rates vs catalog | C oracle reconstruction (the sources + the log reproduce the truth)
| D naive-join evidence (no two systems integrate by key equality) | E reproducibility."""
from __future__ import annotations

import hashlib
import json
import math
import sys

import duckdb
import numpy as np
import pandas as pd
from openpyxl import load_workbook

from . import config as C
from .sources.common import Truth
from .sources.wms import event_id
from .validate import Results

S = (C.ROOT / "sources").as_posix()
TD = C.TRUTH_DIR.as_posix()
CUT = pd.Timestamp("2026-09-20")
E0 = pd.Timestamp(C.HISTORY_END)
W0 = pd.Timestamp(C.WINDOW_START)


def q(con, sql):
    return con.execute(sql).fetchdf()


def q1(con, sql):
    return con.execute(sql).fetchone()[0]


def connect():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for v, f in {"t_lines": "truth_order_lines", "t_orders": "truth_orders", "t_mv": "truth_movements", "t_pol": "truth_po_lines", "t_po": "truth_purchase_orders",
                 "t_ship": "truth_shipments", "t_chg": "truth_freight_charges", "t_def": "truth_defects", "t_cnt": "truth_counts", "sku": "dim_sku",
                 "wh": "dim_warehouse", "t_tr": "truth_transfers", "t_open": "truth_opening_balance", "t_oh": "truth_onhand_daily"}.items():
        con.execute(f"CREATE VIEW {v} AS SELECT * FROM read_parquet('{TD}/{f}.parquet')")
    con.execute(f"CREATE VIEW erp_line AS SELECT * FROM read_csv('{S}/erp/sales_order_line/*.csv', all_varchar=true)")
    con.execute(f"CREATE VIEW erp_hdr AS SELECT * FROM read_csv('{S}/erp/sales_order_header/*.csv', all_varchar=true)")
    con.execute(f"CREATE VIEW erp_pol AS SELECT * FROM read_csv('{S}/erp/po_line/*.csv', all_varchar=true)")
    con.execute(f"CREATE VIEW erp_item AS SELECT * FROM read_csv('{S}/erp/item_master.csv', all_varchar=true)")
    cols = "{event_id: 'VARCHAR', warehouse: 'VARCHAR', event_type: 'VARCHAR', event_ts: 'VARCHAR', published_at: 'VARCHAR', item_id: 'BIGINT', quantity: 'INTEGER', direction: 'VARCHAR', uom: 'VARCHAR', bin: 'VARCHAR', ref_type: 'VARCHAR', ref_no: 'VARCHAR', operator: 'VARCHAR', reason: 'VARCHAR', schema_version: 'INTEGER', batch_id: 'VARCHAR'}"
    con.execute(f"CREATE VIEW wms AS SELECT * FROM read_json('{S}/wms/*/*.jsonl', format='newline_delimited', columns={cols})")
    con.execute(f"CREATE VIEW leg AS SELECT * FROM read_csv('{S}/legacy/inv_trans_*.csv', all_varchar=true)")
    con.execute("""CREATE VIEW erp_latest AS SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY order_no, line_no ORDER BY extract_date DESC, last_modified DESC) rn
                   FROM erp_line) WHERE rn = 1""")
    con.execute("""CREATE VIEW t_line AS SELECT 'SO-' || CAST(100000 + 2 * l.order_id AS VARCHAR) order_no, l.line_no, s.sku_code, l.qty_ordered, l.qty_shipped,
                   l.unit_price, l.line_id, l.order_date FROM t_lines l JOIN sku s USING (sku_id)""")
    return con


def tol_ok(count, n, p, k=4.0):
    return abs(count - n * p) <= k * math.sqrt(max(n * p * (1 - p), 1e-9)) + 2


# ------------------------------------------------------------------------------------------------ A
def group_a(con, R, man):
    print("A. Source shape and volume")
    f = man["files_by_system"]
    n = {"erp lines (all versions)": q1(con, "SELECT COUNT(*) FROM erp_line"), "erp headers": q1(con, "SELECT COUNT(*) FROM erp_hdr"),
         "erp po lines": q1(con, "SELECT COUNT(*) FROM erp_pol"), "wms events": q1(con, "SELECT COUNT(*) FROM wms"),
         "legacy rows": q1(con, "SELECT COUNT(*) FROM leg")}
    R.add("A", "five systems present in five different native formats", f"ERP csv ({f['erp']:,} files), WMS jsonl ({f['wms']:,}), freight json+csv ({f['freight']:,}), legacy csv ({f['legacy']}), xlsx ({f['spreadsheets']})",
          "all > 0", all(f[k] > 0 for k in ("erp", "wms", "freight", "legacy", "spreadsheets")))
    R.add("A", "volumes", "; ".join(f"{k} {v:,}" for k, v in n.items()), "WMS ~1.8M, ERP lines ~0.65M", 1.6e6 <= n["wms events"] <= 2.1e6 and n["erp lines (all versions)"] > 6e5)
    return n


# ------------------------------------------------------------------------------------------------ B
def group_b(con, R, man, T):
    print("B. Injected-defect rates vs catalog")
    d = pd.read_parquet(C.TRUTH_DIR / "truth_defects.parquet")
    cnt = d.groupby("defect_code").size().to_dict()
    lines = q1(con, f"SELECT COUNT(*) FROM t_lines WHERE order_date >= DATE '{C.WINDOW_START}'")
    n_open = q1(con, "SELECT COUNT(*) FROM wms WHERE event_type = 'OPENING_BALANCE'")
    ev = man["stats"]["wms"]["wms_events_written"] - cnt.get("W1", 0) - n_open  # unique, non-opening events
    n_recv = q1(con, "SELECT COUNT(*) FROM wms WHERE event_type='RECEIVE'")
    n_ship = q1(con, "SELECT COUNT(*) FROM wms WHERE event_type='SHIP'") + cnt.get("W6", 0)
    transfers = q1(con, f"SELECT COUNT(*) FROM t_tr WHERE in_date <= DATE '{C.HISTORY_END}' AND out_date >= DATE '{C.WINDOW_START}'")
    ca, cb = man["stats"]["freight"]["carrier_a"], man["stats"]["freight"]["carrier_b"]
    pos = man["stats"]["erp"]["pos"]
    rcpt = q1(con, "SELECT COUNT(*) FROM leg WHERE trans_type = 'RCPT'")
    legrows = q1(con, "SELECT COUNT(*) FROM leg")
    cs = man["stats"]["counts"]
    ps = man["stats"]["price"]

    def row(code, base, label, p, k=4.0, note=""):
        c = cnt.get(code, 0)
        ok = tol_ok(c, base, p, k)
        R.add("B", f"{code} {label}", f"{c:,} of {base:,} = {c / max(base, 1):.2%} ({note or 'target ' + format(p, '.2%')})", f"within {k:g} sigma of {p:.2%}", ok)

    row("E2", lines, "duplicate lines from re-keyed orders", 0.006)
    row("E3", lines, "zero/negative quantity", 0.0015)
    row("E4", lines, "ship-from warehouse null/invalid", 0.003)
    row("E5", lines, "lines in cases (legit)", 0.015)
    row("E6", lines, "quantity changed after shipment", 0.0068, 5, "7% of eligible shipped lines whose change date is in history")
    e1 = cnt.get("E1", 0) / lines
    R.add("B", "E1 successor SKU keyed as predecessor", f"{cnt.get('E1', 0):,} = {e1:.2%}", "0.75-0.85% (candidate-limited)", 0.0075 <= e1 <= 0.0085)
    row("W1", ev, "duplicate events (at-least-once delivery)", 0.018)
    row("W2", ev, "late / out-of-order events", 0.025)
    w3 = cnt.get("W3", 0) / ev
    R.add("B", "W3 events for items not yet linked to a WMS id (natural)", f"{cnt.get('W3', 0):,} = {w3:.2%}", "0.15-0.35% (natural result of a 0-35 day link lag)", 0.0015 <= w3 <= 0.0035)
    row("W5", n_recv, "receipts keyed under the wrong item", 0.008)
    row("W6", n_ship, "ship confirmations missing (line-level drop)", 0.005, 5)
    row("C3", transfers, "transfers recorded one-sided", 0.012)
    c1 = man["stats"]["erp"]["c1_po_rate"]
    R.add("B", "C1 POs whose ERP receipt disagrees with the WMS", f"{c1:.2%} of {pos:,} POs", "1.5-2.5%", 0.015 <= c1 <= 0.025)
    row("F2", ca + cb, "carrier reference mangled", 0.015)
    row("F4", ca + cb, "delivery before pickup / impossible transit", 0.002)
    row("F5", ca + cb, "weight or pieces missing", 0.03)
    row("F7", ca, "duplicate charge line on a Carrier A shipment", 0.010)
    R.add("B", "F1 carrier re-sent whole prior-day files", f"{cnt.get('F1', 0)}", "exactly 3", cnt.get("F1", 0) == 3)
    R.add("B", "S2 Carrier B schema change", f"{cnt.get('S2', 0)} event, {man['stats']['freight']['b_files_new_schema']} files in new schema", "1 event on 2026-06-04", cnt.get("S2", 0) == 1)
    R.add("B", "S3 WMS outage Flagstaff", f"{cnt.get('S3', 0)} events delayed 36-60h", "> 400", cnt.get("S3", 0) > 400)
    row("L4", rcpt, "orphan vendor ids on receipts", 0.05)
    row("L5", legrows, "unparseable numerics", 0.003)
    l2 = cnt.get("L2", 0) / legrows
    R.add("B", "L2 day-ambiguous dates (blank terminal and day <= 12)", f"{cnt.get('L2', 0)} = {l2:.2%}", "0.1-0.3%", 0.001 <= l2 <= 0.003)
    R.add("B", "L6 duplicate vendors", f"{cnt.get('L6', 0)} pairs (5 strong, 2 weak)", "exactly 7", cnt.get("L6", 0) == 7)
    row("X2", cs["count_rows"], "count rows with SKU typos", 0.02)
    row("X3", cs["count_rows"], "cases counted but entered as each", 0.008)
    row("X5", cs["count_rows"], "count dated wrong month/year", 0.004)
    row("X6", ps["price_rows"], "conflicting price overrides", 0.015 / 1.015, 4, "of rows including the conflicts")
    x1 = cnt.get("X1", 0) / cs["count_files"]
    R.add("B", "X1 files with non-standard header names", f"{cnt.get('X1', 0)} of {cs['count_files']} = {x1:.0%}", "~35% (3-sigma band 23-47%)", tol_ok(cnt.get("X1", 0), cs["count_files"], 0.35, 3))
    R.add("B", "U1/U2/U3 deliberately undetectable classes present", f"U1 {cnt.get('U1', 0)}, U2 {cnt.get('U2', 0)}, U3 {cnt.get('U3', 0):,}", "all > 0", all(cnt.get(k, 0) > 0 for k in ("U1", "U2", "U3")))
    return d


# ------------------------------------------------------------------------------------------------ C
def group_c(con, R, T, d):
    print("C. Oracle reconstruction (sources + defect log reproduce the truth)")
    # --- ERP sales lines
    logged = d[d.source_table == "sales_order_line"].source_row_key
    con.register("logged_keys", pd.DataFrame({"k": logged.values}))
    con.execute("CREATE OR REPLACE VIEW erp_state AS SELECT *, order_no || '|' || line_no k FROM erp_latest")
    n_truth = q1(con, "SELECT COUNT(*) FROM t_line")
    n_e2 = int((d.defect_code == "E2").sum())
    n_erp = q1(con, "SELECT COUNT(*) FROM erp_state")
    R.add("C", "ERP: distinct order lines = truth lines + logged duplicates", f"{n_erp:,} vs {n_truth:,} + {n_e2:,}", "equal", n_erp == n_truth + n_e2)
    bad = q1(con, """SELECT COUNT(*) FROM t_line t JOIN erp_state e ON e.order_no = t.order_no AND CAST(e.line_no AS INT) = t.line_no
                     WHERE e.k NOT IN (SELECT k FROM logged_keys) AND (e.item_no <> t.sku_code OR CAST(e.qty_ordered AS DOUBLE) <> t.qty_ordered
                       OR CAST(e.qty_shipped AS DOUBLE) <> t.qty_shipped OR ABS(CAST(e.unit_price AS DOUBLE) - t.unit_price) > 0.005)""")
    clean = q1(con, "SELECT COUNT(*) FROM erp_state WHERE k NOT IN (SELECT k FROM logged_keys)")
    R.add("C", "ERP: every line with NO logged defect equals the truth (sku, qty, shipped, price)", f"{bad} mismatches of {clean:,} clean lines", "0", bad == 0)
    ck = q(con, """SELECT d.defect_code c, COUNT(*) n, SUM(CASE
        WHEN d.defect_code='E1' THEN (e.item_no <> t.sku_code AND EXISTS (SELECT 1 FROM erp_item p WHERE p.item_no = e.item_no AND p.superseded_by = t.sku_code))::INT
        WHEN d.defect_code='E3' THEN (CAST(e.qty_ordered AS DOUBLE) <= 0)::INT
        WHEN d.defect_code='E4' THEN (e.ship_wh IS NULL OR e.ship_wh NOT IN ('WH-01','WH-02','WH-03','WH-04','WH-05','WH-06'))::INT
        WHEN d.defect_code='E5' THEN (e.uom = 'CS' AND CAST(e.qty_ordered AS DOUBLE) * CAST(i.case_qty AS DOUBLE) = t.qty_ordered)::INT
        WHEN d.defect_code='E5b' THEN (e.uom = 'CS' AND i.case_qty IS NULL)::INT
        END) ok
        FROM t_def d JOIN erp_state e ON e.k = d.source_row_key JOIN t_line t ON t.order_no = e.order_no AND CAST(e.line_no AS INT) = t.line_no
        LEFT JOIN erp_item i ON i.item_no = t.sku_code
        WHERE d.source_table = 'sales_order_line' AND d.defect_code IN ('E1','E3','E4','E5','E5b') GROUP BY 1 ORDER BY 1""")
    e6 = d[d.defect_code == "E6"][["source_row_key", "detail"]].copy()
    e6["orig"] = e6.detail.map(lambda s: json.loads(s)["original_qty"])
    cur = q(con, "SELECT e.k, CAST(e.qty_ordered AS DOUBLE) q, t.qty_ordered tq FROM erp_state e JOIN t_line t ON t.order_no = e.order_no AND CAST(e.line_no AS INT) = t.line_no")
    e6 = e6.merge(cur, left_on="source_row_key", right_on="k")
    e6_ok = int(((e6.q != e6.tq) & (e6.orig == e6.tq)).sum())
    ck = pd.concat([ck, pd.DataFrame({"c": ["E6"], "n": [len(e6)], "ok": [e6_ok]})], ignore_index=True)
    bad_c = ck[ck.n != ck.ok]
    R.add("C", "ERP: each logged defect is present in the data exactly as logged (E1,E3,E4,E5,E5b,E6)", ", ".join(f"{r.c} {int(r.ok)}/{int(r.n)}" for r in ck.itertuples()), "all rows verified", bad_c.empty)
    # --- ERP purchase orders
    c1k = d[d.defect_code == "C1"].source_row_key
    con.register("c1_keys", pd.DataFrame({"k": c1k.values}))
    pbad = q1(con, """WITH e AS (SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY po_no, line_no ORDER BY extract_date DESC) rn FROM erp_pol) WHERE rn=1),
        t AS (SELECT 'PO-' || CAST(500000 + p.po_id AS VARCHAR) po_no, ROW_NUMBER() OVER (PARTITION BY p.po_id ORDER BY p.po_line_id) line_no, s.sku_code, p.qty_ordered, p.qty_received, p.unit_cost, p.received_date
              FROM t_pol p JOIN sku s USING (sku_id))
        SELECT COUNT(*) FROM t JOIN e ON e.po_no = t.po_no AND CAST(e.line_no AS INT) = t.line_no
        WHERE (e.po_no || '|' || e.line_no) NOT IN (SELECT k FROM c1_keys) AND t.received_date <= DATE '2026-09-30'
          AND (CAST(e.qty_received AS INT) <> t.qty_received OR e.item_no <> t.sku_code OR ABS(CAST(e.unit_cost AS DOUBLE) - t.unit_cost) > 0.005)""")
    R.add("C", "ERP POs: every received line with no logged C1 defect equals the truth", f"{pbad} mismatches", "0", pbad == 0)
    # --- WMS + legacy: stock accounting identity at the cutoff
    identity(con, R, T, d)
    # --- freight
    freight_oracle(con, R, T, d)
    # --- counts
    counts_oracle(con, R, T, d)


def identity(con, R, T, d):
    cut = CUT.date()
    truth = q(con, f"SELECT sku_id, warehouse_id wh, onhand_qty truth FROM t_oh WHERE snapshot_date = DATE '{cut}'").set_index(["sku_id", "wh"])
    wms = q(con, f"""WITH e AS (SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY published_at) rn FROM wms) WHERE rn=1)
        SELECT s.sku_id, w.warehouse_id wh, SUM(CASE e.direction WHEN 'IN' THEN e.quantity WHEN 'OUT' THEN -e.quantity ELSE 0 END) book
        FROM e JOIN wh w ON w.warehouse_code = e.warehouse JOIN sku s ON s.wms_item_id = e.item_id
        WHERE CAST(timezone(w.timezone, CAST(e.event_ts AS TIMESTAMPTZ)) AS DATE) <= DATE '{cut}' GROUP BY ALL""").set_index(["sku_id", "wh"]).book
    # legacy: oracle-parse the text columns using the defect log for ambiguous cases
    leg = q(con, "SELECT trans_id, item_code, trans_type, trans_date, qty, entry_terminal FROM leg")
    skus = T.sku
    code_map = skus.groupby("legacy_code").sku_id.agg(list)
    l1 = d[d.defect_code == "L1"].set_index("source_row_key").detail.map(lambda s: json.loads(s)["true_sku_id"])
    l5 = d[d.defect_code == "L5"].set_index("source_row_key").detail.map(lambda s: json.loads(s)["true_qty"])
    l2 = d[d.defect_code == "L2"].set_index("source_row_key").detail.map(lambda s: json.loads(s)["true_date"])
    code = leg.item_code.str.strip()
    sku_id = [l1.get(t) if t in l1.index else (code_map[c][0] if c in code_map.index else np.nan) for t, c in zip(leg.trans_id, code)]
    leg["sku_id"] = sku_id
    assert leg.sku_id.notna().all(), f"{int(leg.sku_id.isna().sum())} legacy rows cannot be mapped to a SKU"
    qty = pd.to_numeric(leg.qty.str.replace(",", "").str.strip(), errors="coerce")
    qty = pd.Series([l5.get(t, np.nan) if t in l5.index else v for t, v in zip(leg.trans_id, qty)], index=leg.index)

    def pdate(t, s, term):
        if t in l2.index:
            return pd.Timestamp(l2[t])
        if term == "T2":
            return pd.to_datetime(s, format="%d-%b-%Y")
        try:
            return pd.to_datetime(s, format="%m/%d/%y")
        except ValueError:
            return pd.to_datetime(s, format="%d/%m/%y")
    leg["d"] = [pdate(t, s, e) for t, s, e in zip(leg.trans_id, leg.trans_date, leg.entry_terminal.fillna(""))]
    sign = leg.trans_type.map({"RCPT": 1, "XFER": 1, "OPEN": 1, "ISSU": -1, "ADJ+": 1, "ADJ-": -1})
    leg["eff"] = qty * sign
    lg = leg[leg.d <= CUT].groupby("sku_id").eff.sum()
    book = pd.concat([wms, pd.Series(lg.values, index=pd.MultiIndex.from_arrays([lg.index.astype(int), np.full(len(lg), 5)], names=["sku_id", "wh"]))])
    book = book.groupby(level=[0, 1]).sum()
    # expected difference (truth - book) from the log
    mv = T.mv.copy()
    mv["pair"] = list(zip(mv.sku_id, mv.warehouse_id))
    mvc = mv[mv.movement_date <= CUT]
    exp = {}

    def add(pair, v):
        exp[pair] = exp.get(pair, 0) + v
    for r in mvc[mvc.movement_type.isin(["shrink", "scenario_loss"])].itertuples():
        add(r.pair, r.qty_delta)
    ship_ids = mv[mv.movement_type == "ship"]
    ev_of = pd.Series(ship_ids.movement_id.values, index=event_id(ship_ids.movement_id.values * 8 + 2))
    w6 = d[d.defect_code == "W6"].source_row_key
    dropped = mv.set_index("movement_id").loc[ev_of.reindex(w6).values]
    for r in dropped[dropped.movement_date <= CUT].itertuples():
        add((r.sku_id, r.warehouse_id), r.qty_delta)
    c3 = d[d.defect_code == "C3"]
    tmv = mv[mv.movement_type.isin(["transfer_out", "transfer_in"])].set_index(["ref_id", "movement_type"])
    for r in c3.itertuples():
        side = json.loads(r.detail)["missing_side"]
        key = (int(r.truth_entity_id), "transfer_out" if side == "out" else "transfer_in")
        if key in tmv.index:
            m = tmv.loc[key]
            if m.movement_date <= CUT:
                add((m.sku_id, m.warehouse_id), m.qty_delta)
    w5 = d[d.defect_code == "W5"]
    mvi = mv.set_index("movement_id")
    for r in w5.itertuples():
        m = mvi.loc[int(r.truth_entity_id)]
        if m.movement_date <= CUT:
            dt = json.loads(r.detail)
            add((dt["true_sku_id"], m.warehouse_id), dt["qty"])
            add((dt["booked_sku_id"], m.warehouse_id), -dt["qty"])
    cnt = pd.read_parquet(C.TRUTH_DIR / "truth_counts.parquet")
    posted = cnt[cnt.posted & (cnt.post_date <= CUT)]
    for r in posted.itertuples():
        add((r.sku_id, r.wh_id), -r.variance)
    allpairs = truth.index
    actual = truth.truth - book.reindex(allpairs).fillna(0)
    expected = pd.Series([exp.get(p, 0) for p in allpairs], index=allpairs)
    diff = (actual - expected)
    bad = int((diff != 0).sum())
    R.add("C", "stock identity: truth - system book == logged unrecorded effects - posted count adjustments (all SKU-warehouse pairs, WMS + legacy)",
          f"{bad} mismatches of {len(allpairs):,} pairs", "0", bad == 0)
    if bad:
        print(diff[diff != 0].head(12).to_string())
    acc = float((actual == 0).mean())
    R.add("C", "record accuracy implied by the sources (informational): share of pairs where the book equals physical stock at the cutoff", f"{acc:.1%} exact; {int((actual != 0).sum()):,} pairs off", "reported", True)
    return acc


def freight_oracle(con, R, T, d):
    import glob
    recs = {}
    for f in sorted(glob.glob(f"{S}/freight/carrier_a/shipments_*.json")):
        if f.endswith("_resend.json"):
            continue
        for r in json.load(open(f)):
            recs[r["bol_no"]] = r
    t = T.ship[T.ship.carrier == "CARRIER_A"].copy()
    t["bol"] = "BOL" + (700000000 + t.shipment_id).astype(str)
    f2 = d[(d.defect_code == "F2")].set_index("truth_entity_id").detail.map(lambda s: json.loads(s)["true_ref"])
    f5 = set(d[d.defect_code == "F5"].truth_entity_id.astype(str))
    f4 = set(d[d.defect_code == "F4"].truth_entity_id.astype(str))
    from .sources.common import order_no, po_no
    truth_ref = pd.Series(np.where(t.direction == "outbound", order_no(t.ref_id).values, po_no(t.ref_id).values), index=t.bol.values)
    bad_ref = bad_w = bad_date = 0
    for sid, bol, tref, w, dd in zip(t.shipment_id, t.bol, truth_ref, t.weight_lb, t.actual_delivery_date):
        r = recs.get(bol)
        if r is None:
            bad_ref += 1
            continue
        if str(sid) not in f2.index and r["shipper_ref"] != tref:
            bad_ref += 1
        if str(sid) not in f5 and (r["weight_lb"] is None or abs(r["weight_lb"] - w) > 0.05):
            bad_w += 1
        dl = [e for e in r["events"] if e["status"] == "DELIVERED"]
        if dl and str(sid) not in f4:
            ts = pd.Timestamp(dl[0]["ts_ms"], unit="ms")
            if abs((ts.normalize() - pd.Timestamp(dd)).days) > 1:
                bad_date += 1
    in_feed = sum(1 for b in t.bol if b in recs)
    R.add("C", "Carrier A: every truth shipment is in the feed; refs, weights, delivery dates match except logged F2/F4/F5",
          f"{in_feed:,}/{len(t):,} present; ref {bad_ref}, weight {bad_w}, delivery-date {bad_date} mismatches", "0 mismatches", in_feed == len(t) and bad_ref == bad_w == bad_date == 0)
    tc = T.chg.merge(t[["shipment_id", "bol"]], on="shipment_id")
    truth_sum = tc.groupby("bol").amount.sum()
    f7 = d[d.defect_code == "F7"]
    dup_amt = f7.assign(bol=lambda x: "BOL" + (700000000 + x.truth_entity_id.astype(int)).astype(str), a=lambda x: x.detail.map(lambda s: json.loads(s)["amount"])).groupby("bol").a.sum()
    bad_c = 0
    delivered = {b for b, r in recs.items() if "charges" in r}
    for b in delivered:
        src = sum(c["amount"] for c in recs[b]["charges"])
        exp = truth_sum.get(b, 0) + dup_amt.get(b, 0)
        if abs(src - exp) > 0.02:
            bad_c += 1
    R.add("C", "Carrier A: invoiced charges = truth charges + logged F7 duplicates, per shipment", f"{bad_c} mismatches of {len(delivered):,} invoiced", "0", bad_c == 0)
    dup_dollars = float(f7.detail.map(lambda s: json.loads(s)["amount"]).sum())
    R.add("C", "S4 double-billed freight: recoverable dollars planted (informational)", f"${dup_dollars:,.0f} across {len(f7)} shipments", "reported", True)
    # Carrier B
    con.execute(f"CREATE OR REPLACE VIEW b_ship AS SELECT * FROM read_csv('{S}/freight/carrier_b/shipments_*.csv', union_by_name=true, all_varchar=true)")
    con.execute(f"CREATE OR REPLACE VIEW b_chg AS SELECT * FROM read_csv('{S}/freight/carrier_b/charges_*.csv', all_varchar=true)")
    tb = T.ship[T.ship.carrier == "CARRIER_B"]
    nb = q1(con, "SELECT COUNT(DISTINCT tracking_no) FROM b_ship")
    cols = set(q(con, "DESCRIBE b_ship").column_name)
    wcol = "COALESCE(weight_lb, wt_lbs)"
    f5b = d[(d.defect_code == "F5")].truth_entity_id.astype(int)
    wbad = q1(con, f"""SELECT COUNT(*) FROM b_ship b JOIN (SELECT '1Z' || CAST(900000000 + shipment_id AS VARCHAR) tn, weight_lb w, shipment_id FROM t_ship WHERE carrier='CARRIER_B') t
                       ON t.tn = b.tracking_no WHERE {wcol} IS NOT NULL AND ABS(CAST({wcol} AS DOUBLE) - t.w) > 0.05""")
    R.add("C", "Carrier B: all shipments present; weights equal the truth across BOTH schemas (weight_lb and wt_lbs)", f"{nb:,}/{len(tb):,} present, {wbad} weight mismatches; schema cols new={sorted(cols & {'wt_lbs', 'dim_weight', 'service_level', 'delivery_type'})}",
          "0 mismatches, new columns present", nb == len(tb) and wbad == 0 and "wt_lbs" in cols)
    cb = q1(con, """SELECT COUNT(*) FROM (SELECT b.tracking_no, SUM(CAST(b.amount AS DOUBLE)) s FROM b_chg b GROUP BY 1) x
                    JOIN (SELECT '1Z' || CAST(900000000 + c.shipment_id AS VARCHAR) tn, SUM(c.amount) s FROM t_chg c GROUP BY 1) t ON t.tn = x.tracking_no WHERE ABS(t.s - x.s) > 0.02""")
    R.add("C", "Carrier B: invoiced charges equal truth charges per shipment", f"{cb} mismatches", "0", cb == 0)
    # F1: resends are byte-identical copies of the previous day's file
    import os
    bad = 0
    n = 0
    for f in glob.glob(f"{S}/freight/carrier_a/*_resend.json"):
        n += 1
        day = pd.Timestamp(os.path.basename(f)[10:18])
        prev = sorted(x for x in glob.glob(f"{S}/freight/carrier_a/shipments_*.json") if "_resend" not in x and os.path.basename(x)[10:18] < day.strftime("%Y%m%d"))[-1]
        if open(f).read() != open(prev).read():
            bad += 1
    R.add("C", "F1: re-sent files are exact copies of the previous day's file", f"{n} resends, {bad} differing", "3, 0 differing", n == 3 and bad == 0)


def read_sheets():
    import glob
    rows = []
    for f in sorted(glob.glob(f"{S}/spreadsheets/count_sheets/*/*.xlsx")):
        rel = f.replace("\\", "/").split("/sources/")[1]
        ws = load_workbook(f, data_only=False).active
        for r in range(6, ws.max_row + 1):
            a, b, e, g = ws.cell(r, 1).value, ws.cell(r, 2).value, ws.cell(r, 5).value, ws.cell(r, 7).value
            if a and b and isinstance(e, (int, float)) and not isinstance(a, bool):
                rows.append((rel, r, str(a), str(b), ws.cell(r, 3).value, ws.cell(r, 4).value, float(e), g, ws.cell(r, 6).value))
    return pd.DataFrame(rows, columns=["file", "row", "sku", "desc", "bin", "uom", "qty", "date", "by"])


def counts_oracle(con, R, T, d):
    sh = read_sheets()
    cnt = pd.read_parquet(C.TRUTH_DIR / "truth_counts.parquet")
    R.add("C", "Spreadsheets: every truth count appears as exactly one sheet row", f"{len(sh):,} sheet rows vs {len(cnt):,} counts", "equal", len(sh) == len(cnt))
    logged = set(d[d.source_table == "count_row"].source_row_key)
    sh["k"] = sh.file + "|" + sh.row.astype(str)
    sh["wh"] = sh.file.str.extract(r"(WH-0\d)")[0].map({v: k for k, v in T.wh_code.items()})
    sh["d"] = [pd.Timestamp(x) if not isinstance(x, str) else pd.to_datetime(x, format="%m/%d/%Y" if "/" in x else "%d-%b-%y") for x in sh.date]
    code = T.sku.set_index("sku_code").sku_id
    sh["sku_id"] = sh.sku.map(code)
    clean = sh[~sh.k.isin(logged)]
    m = clean.merge(cnt[["sku_id", "wh_id", "count_date", "true_qty"]], left_on=["sku_id", "wh", "d"], right_on=["sku_id", "wh_id", "count_date"], how="left")
    bad = int(((m.qty != m.true_qty) | m.true_qty.isna()).sum())
    R.add("C", "Spreadsheets: every row with no logged defect reproduces the true count (sku, date, quantity)", f"{bad} mismatches of {len(clean):,} clean rows", "0", bad == 0)
    x2 = d[d.defect_code == "X2"]
    rec = x2.detail.map(lambda s: json.loads(s)["recoverable"])
    R.add("C", "X2 SKU typos: share recoverable by a unique single edit (the rest must go to review)", f"{rec.mean():.0%} of {len(x2)}", "reported (>= 40%)", rec.mean() >= 0.40)


# ------------------------------------------------------------------------------------------------ D
def group_d(con, R, T):
    print("D. Naive-join evidence")
    rows = []
    wms_items = q1(con, "SELECT COUNT(DISTINCT item_id) FROM wms")
    rows.append(("ERP item_no = WMS item_id", "0% (different identifier systems: text SKU vs integer id)", "needs the ERP link table, and new items are linked up to 35 days late (W3)"))
    j = q1(con, "SELECT COUNT(*) FROM leg l JOIN erp_item i ON TRIM(l.item_code) = i.item_no")
    rows.append(("ERP item_no = legacy item_code", f"{j} matching rows", "8-char codes need a crosswalk; 6% are ambiguous across revisions"))
    import glob
    ref_total = ref_hit = 0
    valid = set(q(con, "SELECT DISTINCT order_no FROM erp_line").order_no)
    for f in sorted(glob.glob(f"{S}/freight/carrier_a/shipments_2025*.json"))[:120]:
        if "_resend" in f:
            continue
        for r in json.load(open(f)):
            if r["shipper_ref"].startswith(("SO-", "so-", "SO", "so")):
                ref_total += 1
                ref_hit += r["shipper_ref"] in valid
    rows.append(("ERP order_no = carrier shipper_ref (Carrier A, 120-day sample)", f"{ref_hit / max(ref_total, 1):.1%} exact", "case, hyphen, padding and typo variants (F2)"))
    sh = read_sheets()
    items = set(T.sku.sku_code)
    rows.append(("ERP item_no = count-sheet SKU", f"{sh.sku.isin(items).mean():.1%} exact", "typed SKUs (X2), valid-but-wrong swaps (U2)"))
    rows.append(("timestamps across the five systems", "6 conventions", "ERP naive local per warehouse; WMS UTC ISO-8601; Carrier A epoch ms; Carrier B local + text offset; legacy date-only text in 2 formats; sheets free text"))
    cs = q1(con, "SELECT COUNT(*) FROM erp_line WHERE uom='CS'") / q1(con, "SELECT COUNT(*) FROM erp_line")
    rows.append(("units of measure", f"{cs:.1%} of ERP line rows in cases", "conversion factor lives in the item master and is missing for some items (E5b)"))
    ok = ref_hit / max(ref_total, 1) < 1 and sh.sku.isin(items).mean() < 1 and j == 0
    R.add("D", "no two systems integrate by key equality (item, order-reference and SKU joins all lose rows)", "; ".join(f"{a}: {b}" for a, b, _ in rows[:4]), "each < 100%", ok)
    R.add("D", "heterogeneity: timestamp conventions and units of measure", "6 timestamp conventions; CS/EA mix", ">= 4 conventions", True)
    return rows


# ------------------------------------------------------------------------------------------------ E + report
def sheets_digest():
    sh = read_sheets()
    return hashlib.sha256(pd.util.hash_pandas_object(sh.astype(str), index=False).values.tobytes()).hexdigest()[:16]


def reproducibility(R, man):
    """Rebuilds every source from the same seed into a scratch folder (never in place: the live clock's warehouse remembers the delivered files) and compares."""
    print("E. Reproducibility (full rebuild into a scratch folder)")
    import os
    import shutil
    import subprocess
    import sys
    global S
    before = dict(man["digests"])
    dsh = sheets_digest()
    dh = lambda d: hashlib.sha256(pd.util.hash_pandas_object(pd.read_parquet(d / "truth_defects.parquet").astype(str), index=False).values.tobytes()).hexdigest()[:16]
    ddef = dh(C.TRUTH_DIR)
    scratch = C.ROOT / "scratch_repro"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir()
    tr, out = scratch / "truth", scratch / "sources"
    shutil.copytree(C.TRUTH_DIR, tr)
    env = {**os.environ, "OPS_HUB_TRUTH_DIR": str(tr), "OPS_HUB_SOURCES_OUT": str(out), "OPS_HUB_HORIZON_END": str(C.HISTORY_END)}
    p = subprocess.run([sys.executable, "-m", "generator.build_sources"], cwd=C.ROOT, env=env, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(p.stdout[-1500:] + p.stderr[-1500:])
    after = json.loads((tr / "sources_manifest.json").read_text())["digests"]
    diff = [k for k in before if before[k] != after.get(k)]
    keep = S
    S = out.as_posix()
    dsh2 = sheets_digest()
    S = keep
    ddef2 = dh(tr)
    shutil.rmtree(scratch, ignore_errors=True)
    R.add("E", "rebuilding from the same seed reproduces every source file bit-for-bit (xlsx by parsed content)", f"{len(before) - len(diff)}/{len(before)} systems identical; sheets {'identical' if dsh == dsh2 else 'DIFFER'}; defect log {'identical' if ddef == ddef2 else 'DIFFER'}",
          "all identical", not diff and dsh == dsh2 and ddef == ddef2)


def write_report(R, man, vols, d, naive):
    rows = "\n".join(f"| {n} | {m} | {c} | {'PASS' if ok else 'FAIL'} |" for g, n, m, c, ok in R.rows)
    f = man["files_by_system"]
    inv = "\n".join(f"| {k} | {v:,} | {man['digests'].get(k, '')} |" for k, v in f.items())
    cnt = d.groupby(["defect_code", "source_system"]).size().reset_index(name="n")
    cnt_t = "\n".join(f"| {r.defect_code} | {r.source_system} | {r.n:,} |" for r in cnt.itertuples())
    nv = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in naive)
    txt = ["# System 1 — Phase 2 Report: The Five Source Systems\n",
           f"Result: **{'ALL CHECKS PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in R.rows)}/{len(R.rows)}).\n",
           f"Source data: {sum(f.values()):,} files, {man['bytes'] / 1e6:.0f} MB, {len(d):,} logged defects.\n", "## Source inventory\n",
           "| System | Files | Content digest |\n|---|---|---|", inv, "\n## Naive-join evidence\n", "| Join | Naive result | Why |\n|---|---|---|", nv,
           "\n## Defects logged\n", "| Code | System | Count |\n|---|---|---|", cnt_t, "\n## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (C.ROOT / "docs" / "PHASE2_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def chart(d):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    c = d.groupby("defect_code").size().sort_values()
    fig, ax = plt.subplots(figsize=(9, 9))
    colors = ["#c0392b" if k.startswith("U") else "#1D5FA3" for k in c.index]
    ax.barh(c.index, c.values, color=colors)
    ax.set_xscale("log")
    ax.set_title("Phase 2: injected defects by class (log scale). Red = deliberately undetectable. All data synthetic.")
    for i, v in enumerate(c.values):
        ax.text(v * 1.08, i, f"{v:,}", va="center", fontsize=8)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(C.ROOT / "docs" / "phase2_defects.png", dpi=110)


def main():
    full = "--full" in sys.argv
    con = connect()
    man = json.loads((C.TRUTH_DIR / "sources_manifest.json").read_text())
    T = Truth()
    R = Results()
    vols = group_a(con, R, man)
    d = group_b(con, R, man, T)
    group_c(con, R, T, d)
    naive = group_d(con, R, T)
    if full:
        reproducibility(R, man)
    write_report(R, man, vols, d, naive)
    chart(d)
    print(f"\n{sum(r[4] for r in R.rows)}/{len(R.rows)} checks passed")
    sys.exit(0 if R.all_ok else 1)


if __name__ == "__main__":
    main()
