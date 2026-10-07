"""Phase 1 gate: validates the truth store. Usage: python -m generator.validate [--full]
--full also runs the determinism and live-clock resume tests (two extra full simulations, ~1.5 min)."""
from __future__ import annotations

import json
import sys
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from . import config as C

TD = str(C.TRUTH_DIR).replace("\\", "/")
W = C.WINDOW_START
E = C.HISTORY_END


def connect():
    con = duckdb.connect()
    views = {"mv": "truth_movements", "ol": "truth_order_lines", "od": "truth_orders", "po": "truth_purchase_orders",
             "pol": "truth_po_lines", "tr": "truth_transfers", "sh": "truth_shipments", "fc": "truth_freight_charges",
             "oh": "truth_onhand_daily", "ob": "truth_opening_balance", "sku": "dim_sku", "cust": "dim_customer",
             "wh": "dim_warehouse", "cal": "dim_calendar", "ent": "truth_scenario_entities", "vend": "dim_vendor"}
    for v, f in views.items():
        con.execute(f"CREATE VIEW {v} AS SELECT * FROM read_parquet('{TD}/{f}.parquet')")
    return con


class Results:
    def __init__(self):
        self.rows = []

    def add(self, group, name, measured, criterion, ok):
        self.rows.append((group, name, measured, criterion, bool(ok)))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {measured}   (need {criterion})")

    @property
    def all_ok(self):
        return all(r[4] for r in self.rows)


def q1(con, sql):
    return con.execute(sql).fetchone()[0]


def integrity(con, R):
    print("A. Integrity (must be exact)")
    mism, total = con.execute(f"""
        WITH net AS (SELECT sku_id, warehouse_id, movement_date d, SUM(qty_delta) q FROM mv GROUP BY ALL),
        j AS (SELECT s.snapshot_date d, s.sku_id, s.warehouse_id, s.onhand_qty, COALESCE(n.q, 0) q FROM oh s
              LEFT JOIN net n ON n.sku_id = s.sku_id AND n.warehouse_id = s.warehouse_id AND n.d = s.snapshot_date),
        c AS (SELECT *, SUM(q) OVER (PARTITION BY sku_id, warehouse_id ORDER BY d) cumq FROM j)
        SELECT COUNT(*) FILTER (WHERE o.onhand_qty + c.cumq <> c.onhand_qty), COUNT(*)
        FROM c JOIN ob o ON o.sku_id = c.sku_id AND o.warehouse_id = c.warehouse_id""").fetchone()
    R.add("A", "stock ledger reconciles to daily on-hand truth", f"{mism:,} mismatches of {total:,} SKU-warehouse-days", "0", mism == 0)
    mn = q1(con, "SELECT MIN(onhand_qty) FROM oh")
    R.add("A", "on-hand never negative", f"min {mn}", ">= 0", mn >= 0)
    n = q1(con, "SELECT COUNT(*) FROM ol WHERE qty_shipped > qty_ordered")
    R.add("A", "no line ships more than ordered", f"{n} lines", "0", n == 0)
    n = q1(con, "SELECT COUNT(*) FROM mv WHERE movement_type='ship' AND ref_id NOT IN (SELECT line_id FROM ol)")
    R.add("A", "every ship movement references a known order line", f"{n} orphans", "0", n == 0)
    n = q1(con, f"""SELECT COUNT(*) FROM (SELECT p.po_line_id, p.qty_received, COALESCE(SUM(m.qty_delta),0) got FROM pol p
                   LEFT JOIN mv m ON m.movement_type='receipt' AND m.ref_id=p.po_line_id WHERE p.received_date <= DATE '{E}'
                   GROUP BY ALL HAVING p.qty_received <> got)""")
    open_pl = q1(con, f"SELECT COUNT(*) FROM pol WHERE received_date > DATE '{E}'")
    R.add("A", "receipt movements equal PO-line received quantities (completed receipts)", f"{n} mismatches; {open_pl:,} PO lines still in transit at end", "0", n == 0)
    n = q1(con, f"""SELECT COUNT(*) FROM (SELECT t.transfer_id FROM tr t LEFT JOIN mv m ON m.ref_type='transfer' AND m.ref_id=t.transfer_id
                    WHERE t.in_date <= DATE '{E}' AND t.out_date >= DATE '{W}' GROUP BY t.transfer_id, t.qty
                    HAVING SUM(CASE WHEN m.movement_type='transfer_out' THEN -m.qty_delta ELSE 0 END) <> t.qty
                        OR SUM(CASE WHEN m.movement_type='transfer_in' THEN m.qty_delta ELSE 0 END) <> t.qty)""")
    R.add("A", "completed transfers move identical quantity out and in", f"{n} unbalanced", "0", n == 0)
    n = q1(con, """SELECT (SELECT COUNT(*) FROM ol WHERE sku_id NOT IN (SELECT sku_id FROM sku)) +
                          (SELECT COUNT(*) FROM od WHERE customer_id NOT IN (SELECT customer_id FROM cust)) +
                          (SELECT COUNT(*) FROM pol WHERE sku_id NOT IN (SELECT sku_id FROM sku)) +
                          (SELECT COUNT(*) FROM ol WHERE order_id NOT IN (SELECT order_id FROM od)) +
                          (SELECT COUNT(*) FROM pol WHERE po_id NOT IN (SELECT po_id FROM po)) +
                          (SELECT COUNT(*) FROM fc WHERE shipment_id NOT IN (SELECT shipment_id FROM sh))""")
    R.add("A", "foreign keys resolve (lines, orders, POs, charges)", f"{n} orphans", "0", n == 0)
    n = q1(con, "SELECT COUNT(*) FROM (SELECT order_id, sku_id FROM ol GROUP BY ALL HAVING COUNT(*) > 1)")
    R.add("A", "no duplicate SKU within an order (keeps defect E2 distinguishable)", f"{n} duplicates", "0", n == 0)
    n = q1(con, """SELECT COUNT(*) FROM mv m JOIN cal c ON c.date = m.movement_date
                   WHERE m.movement_type IN ('ship') AND NOT c.is_open_day""") + \
        q1(con, """SELECT COUNT(*) FROM mv m JOIN cal c ON c.date = m.movement_date
                   WHERE m.movement_type IN ('receipt','transfer_in') AND NOT c.is_receiving_day""")
    R.add("A", "no shipping on closed days, no receiving on non-receiving days", f"{n} violations", "0", n == 0)
    n = q1(con, """SELECT COUNT(*) FROM ol l JOIN sku s USING (sku_id)
                   WHERE (s.lifecycle_kind = 'superseded' AND l.order_date > s.discontinue_date + 30)
                      OR (s.lifecycle_kind IN ('successor','new_launch') AND l.order_date < s.intro_date)""")
    R.add("A", "SKU lifecycle respected (no demand outside intro/discontinue window)", f"{n} violations", "0", n == 0)
    # timezone handling: local clock times must stay inside 07:00-17:59 in BOTH winter and summer for every warehouse;
    # a DST error would push summer (or winter) activity to 06:xx or 18:xx
    loc = con.execute("""SELECT w.warehouse_code wh, EXTRACT(month FROM m.movement_date) mo,
                         MIN(EXTRACT(hour FROM timezone(w.timezone, m.ts_utc))) mn, MAX(EXTRACT(hour FROM timezone(w.timezone, m.ts_utc))) mx
                         FROM mv m JOIN wh w USING (warehouse_id) WHERE m.movement_type IN ('ship','receipt','transfer_in')
                         GROUP BY ALL ORDER BY 1, 2""").fetchdf()
    ok = bool(((loc.mn >= 7) & (loc.mx <= 17)).all())
    both = loc[loc.mo.isin([1, 7])]
    R.add("A", "movement local times stay 07:00-17:59 in every month for every warehouse (DST handled; LV/ABQ/ELP shift 1h in UTC)",
          f"local hours {int(loc.mn.min())}-{int(loc.mx.max())} across {len(loc)} warehouse-months; Jan+Jul checked {len(both)}", "07-17", ok)


def calibration(con, R):
    print("B. Calibration to spec")
    n = q1(con, f"SELECT COUNT(*) FROM ol WHERE order_date >= DATE '{W}'")
    R.add("B", "order lines in window", f"{n:,}", "612,000 ±3%", abs(n / 612000 - 1) <= 0.03)
    no = q1(con, f"SELECT COUNT(*) FROM od WHERE order_date >= DATE '{W}'")
    R.add("B", "orders in window", f"{no:,}", "180,000 ±5%", abs(no / 180000 - 1) <= 0.05)
    R.add("B", "lines per order", f"{n / no:.2f}", "3.4 ±0.2", abs(n / no - 3.4) <= 0.2)
    rev = q1(con, f"SELECT SUM(qty_ordered * unit_price) FROM ol WHERE order_date >= DATE '{W}'") / ((E - W).days + 1) * 365
    R.add("B", "annual revenue (ordered, window average)", f"${rev / 1e6:.1f}M", "$48M ±6%", abs(rev / 48e6 - 1) <= 0.06)
    n = q1(con, f"SELECT COUNT(*) FROM sku WHERE discontinue_date IS NULL OR discontinue_date > DATE '{E}'")
    R.add("B", "active SKUs at end of history", f"{n:,}", "2,500", n == 2500)
    ns = q1(con, "SELECT COUNT(*) FROM sku")
    R.add("B", "total SKUs incl. discontinued", f"{ns:,}", "2,800", ns == 2800)
    amb = q1(con, "SELECT COUNT(*) FROM sku WHERE legacy_code IN (SELECT legacy_code FROM sku GROUP BY legacy_code HAVING COUNT(*) > 1)") / ns
    R.add("B", "SKUs with an ambiguous legacy code (feeds defect L1)", f"{amb:.1%}", "~6% (5-7%)", 0.05 <= amb <= 0.07)
    R.add("B", "warehouses / customers / vendors", f"{q1(con, 'SELECT COUNT(*) FROM wh')} / {q1(con, 'SELECT COUNT(*) FROM cust'):,} / {q1(con, 'SELECT COUNT(*) FROM vend')}",
          "6 / 1,600 / 140", (q1(con, "SELECT COUNT(*) FROM wh"), q1(con, "SELECT COUNT(*) FROM cust"), q1(con, "SELECT COUNT(*) FROM vend")) == (6, 1600, 140))


def realism(con, R):
    print("C. Realism")
    fill = q1(con, f"SELECT AVG(CASE WHEN line_status = 'filled_same_day' THEN 1.0 ELSE 0.0 END) FROM ol WHERE order_date >= DATE '{W}'")
    R.add("C", "same-day full line fill rate", f"{fill:.1%}", "92-99%", 0.92 <= fill <= 0.99)
    inv = q1(con, "SELECT AVG(v) FROM (SELECT snapshot_date, SUM(onhand_qty * s.unit_cost) v FROM oh JOIN sku s USING (sku_id) GROUP BY ALL)")
    cogs = q1(con, "SELECT SUM(-m.qty_delta * s.unit_cost) FROM mv m JOIN sku s USING (sku_id) WHERE m.movement_type = 'ship'") / ((E - W).days + 1) * 365
    R.add("C", "inventory turns (COGS / average inventory)", f"{cogs / inv:.2f} (avg inventory ${inv / 1e6:.1f}M)", "3-8", 3 <= cogs / inv <= 8)
    shr = q1(con, "SELECT SUM(-m.qty_delta * s.unit_cost) FROM mv m JOIN sku s USING (sku_id) WHERE m.movement_type = 'shrink'") / ((E - W).days + 1) * 365
    R.add("C", "shrink as % of average inventory value per year", f"{shr / inv:.2%}", "0.2-0.45%", 0.002 <= shr / inv <= 0.0045)
    rev = q1(con, f"SELECT SUM(qty_ordered * unit_price) FROM ol WHERE order_date >= DATE '{W}'") / ((E - W).days + 1) * 365
    fr = q1(con, f"SELECT SUM(c.amount) FROM fc c JOIN sh s USING (shipment_id) WHERE s.carrier IN ('CARRIER_A','CARRIER_B') AND s.ship_date >= DATE '{W}'") / ((E - W).days + 1) * 365
    R.add("C", "external carrier freight as % of revenue", f"{fr / rev:.1%} (${fr / 1e6:.1f}M/yr)", "2-7%", 0.02 <= fr / rev <= 0.07)
    z = q1(con, "SELECT AVG(CASE WHEN o.onhand_qty = 0 THEN 1.0 ELSE 0.0 END) FROM oh o JOIN sku s USING (sku_id) WHERE s.abc_class='A' AND s.lifecycle_kind='continuing'")
    R.add("C", "A-item SKU-warehouse-days at zero stock", f"{z:.1%}", "0.5-5%", 0.005 <= z <= 0.05)
    s = con.execute("""SELECT s.category_id c, EXTRACT(month FROM l.order_date) mo, COUNT(*) n FROM ol l JOIN sku s USING (sku_id)
                       WHERE l.order_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' GROUP BY ALL""").fetchdf().pivot(index="c", columns="mo", values="n")
    roof = s.loc[2, 7] / s.loc[2, 1]
    ins = s.loc[3, 1] / s.loc[3, 7]
    hv_mid = (s.loc[7, 4] + s.loc[7, 5]) / 2
    hvac = min(s.loc[7, 7], s.loc[7, 1]) / hv_mid
    R.add("C", "seasonality: Roofing July / January lines", f"{roof:.2f}x", "2.0-3.2x", 2.0 <= roof <= 3.2)
    R.add("C", "seasonality: Insulation January / July lines", f"{ins:.2f}x", "1.6-2.6x", 1.6 <= ins <= 2.6)
    R.add("C", "seasonality: HVAC peaks in both summer and winter (bimodal)", f"peaks/shoulder-spring = {hvac:.2f}x", "> 1.15x", hvac > 1.15)
    par = q1(con, """WITH t AS (SELECT sku_id, COUNT(*) n FROM ol GROUP BY ALL), r AS (SELECT n, ROW_NUMBER() OVER (ORDER BY n DESC) rk, COUNT(*) OVER () tot FROM t)
                     SELECT SUM(n) FILTER (WHERE rk <= tot * 0.2) / SUM(n) FROM r""")
    R.add("C", "Pareto: top 20% of SKUs share of lines", f"{par:.0%}", "65-90%", 0.65 <= par <= 0.90)
    sat = con.execute("""WITH d AS (SELECT l.order_date, COUNT(*) n FROM ol l GROUP BY ALL)
                         SELECT AVG(n) FILTER (WHERE dayofweek(order_date) = 6) / AVG(n) FILTER (WHERE dayofweek(order_date) IN (2,3,4))
                         FROM d JOIN cal c ON c.date = d.order_date WHERE c.is_open_day""").fetchone()[0]
    R.add("C", "Saturday volume relative to Tue-Thu", f"{sat:.2f}", "0.35 ±0.12", abs(sat - 0.35) <= 0.12)
    conc = q1(con, """WITH t AS (SELECT o.customer_id, SUM(l.qty_ordered * l.unit_price) v FROM ol l JOIN od o USING (order_id) GROUP BY ALL),
                      r AS (SELECT v, ROW_NUMBER() OVER (ORDER BY v DESC) rk, COUNT(*) OVER () tot FROM t) SELECT SUM(v) FILTER (WHERE rk <= tot*0.1) / SUM(v) FROM r""")
    R.add("C", "customer concentration: top 10% of accounts' revenue share", f"{conc:.0%}", "30-65%", 0.30 <= conc <= 0.65)
    bo = q1(con, f"SELECT AVG(CASE WHEN line_status <> 'filled_same_day' THEN 1.0 ELSE 0.0 END) FROM ol WHERE order_date >= DATE '{W}'")
    R.add("C", "share of lines backordered at any point", f"{bo:.1%}", "<= 8%", bo <= 0.08)


def scenarios(con, R):
    print("D. Scenarios")
    ser = con.execute("""SELECT o.snapshot_date d, e.scenario_id sc, SUM(o.onhand_qty) onhand, SUM(o.backlog_qty) backlog,
                         AVG(CASE WHEN o.onhand_qty = 0 THEN 1.0 ELSE 0.0 END) zero_share, COUNT(*) n
                         FROM oh o JOIN ent e ON e.sku_id = o.sku_id AND e.warehouse_id = (CASE WHEN e.scenario_id='S1' THEN 5 ELSE 4 END)
                         AND o.warehouse_id = e.warehouse_id GROUP BY ALL ORDER BY 1""").fetchdf()
    s1 = ser[ser.sc == "S1"].set_index("d")
    n1 = int(s1.n.iloc[0])
    pre = s1.loc[pd.Timestamp(C.S1_START) - pd.Timedelta(days=1), "onhand"] / n1
    post = s1.loc[pd.Timestamp(C.S1_START) + pd.Timedelta(days=14), "onhand"] / n1
    bk = s1.loc[pd.Timestamp(C.S1_DISCOVERED), "backlog"]
    rec = s1.loc[pd.Timestamp(C.S1_DISCOVERED) + pd.Timedelta(days=45), "onhand"] / n1
    R.add("D", "S1 Albuquerque phantom stock: true on-hand collapses after the loss", f"{pre:.0f} -> {post:.1f} units/SKU", "post <= 15% of pre", post <= 0.15 * pre)
    R.add("D", "S1: unfilled demand accumulated while the book showed stock", f"{int(bk):,} backordered units at discovery", ">= 1,000", bk >= 1000)
    R.add("D", "S1: stock recovers after discovery and restock", f"{rec:.0f} units/SKU 45d after discovery", ">= 50% of pre-loss", rec >= 0.5 * pre)
    s5 = ser[ser.sc == "S5"].set_index("d")
    ws, we = pd.Timestamp(C.S5_START), pd.Timestamp(C.S5_END)
    py = pd.Timedelta(days=365)
    z_now = s5.loc[ws:we, "zero_share"].mean()
    z_prev = s5.loc[ws - py:we - py, "zero_share"].mean()
    R.add("D", "S5 Las Vegas surge: out-of-stock share, surge window vs same window prior year", f"{z_now:.1%} vs {z_prev:.1%}", ">= 3x and >= 8%", z_now >= 3 * z_prev and z_now >= 0.08)
    r = con.execute(f"""SELECT
        SUM(CASE WHEN l.order_date BETWEEN DATE '{C.S5_START}' AND DATE '{C.S5_END}' THEN 1 ELSE 0 END) now_n,
        SUM(CASE WHEN l.order_date BETWEEN DATE '{C.S5_START}' - 365 AND DATE '{C.S5_END}' - 365 THEN 1 ELSE 0 END) prev_n,
        SUM(CASE WHEN l.order_date BETWEEN DATE '2026-04-01' AND DATE '2026-05-31' OR l.order_date BETWEEN DATE '2026-08-01' AND DATE '2026-09-30' THEN 1 ELSE 0 END) base_now,
        SUM(CASE WHEN l.order_date BETWEEN DATE '2025-04-01' AND DATE '2025-05-31' OR l.order_date BETWEEN DATE '2025-08-01' AND DATE '2025-09-30' THEN 1 ELSE 0 END) base_prev
        FROM ol l JOIN od o USING (order_id) JOIN ent e ON e.scenario_id='S5' AND e.sku_id = l.sku_id AND e.warehouse_id = o.warehouse_id""").fetchone()
    ratio = (r[0] / max(r[1], 1)) / (r[2] / max(r[3], 1))
    R.add("D", "S5: demand multiplier realised (surge YoY / same SKUs' non-surge YoY, which controls for growth and noise)",
          f"{ratio:.2f}x ({int(r[0])} vs {int(r[1])} lines)", "2.0-2.8x (nominal 2.4)", 2.0 <= ratio <= 2.8)
    return ser


def reproducibility(R):
    print("E. Reproducibility (full simulations)")
    from datetime import timedelta
    from .run_history import build_tables, table_hash
    from .simulate import Recorder, Sim
    meta = json.loads((C.TRUTH_DIR / "truth_meta.json").read_text())
    sim = Sim()
    sim.run(C.WARMUP_START, E)
    T = build_tables(sim)
    bad = [k for k, t in T.items() if table_hash(t) != meta["hashes"][k]]
    R.add("E", "same seed reproduces every truth table bit-for-bit", f"{len(T) - len(bad)}/{len(T)} tables identical", "all", not bad)
    ids = {"move": "movement_id", "order": "order_id", "line": "line_id", "po": "po_id", "po_line": "po_line_id",
           "transfer": "transfer_id", "ship": "shipment_id", "charge": "charge_id"}
    cont = Sim()
    cont.run(C.WARMUP_START, date(2026, 10, 3))
    rec = Recorder()
    live = Sim.load_state(C.TRUTH_DIR / "state_end_of_history.pkl", rec)
    start = dict(live.next_ids)
    live.run(date(2026, 10, 1), date(2026, 10, 3))
    diffs = []
    for t, idc in ids.items():
        a = cont.rec.frame(t)
        a = a[a[idc] >= start[{"move": "move", "order": "order", "line": "line", "po": "po", "po_line": "po_line", "transfer": "transfer", "ship": "ship", "charge": "charge"}[t]]]
        b = live.rec.frame(t)
        a = a.sort_values(idc).reset_index(drop=True)
        b = b.sort_values(idc).reset_index(drop=True) if len(b) else b
        if len(a) != len(b) or not a.equals(b):
            diffs.append(f"{t}({len(a)} vs {len(b)})")
    for k in ("onhand", "backlog", "on_order"):
        if not np.array_equal(np.vstack(cont.rec.t["snap"][k])[-3:], np.vstack(live.rec.t["snap"][k])):
            diffs.append(f"snap.{k}")
    R.add("E", "live clock: resuming from saved state matches a continuous run (3 days)", "identical" if not diffs else "DIFF " + ", ".join(diffs), "identical", not diffs)


def write_report(R, ser, con, full):
    rows = "\n".join(f"| {n} | {m} | {c} | {'PASS' if ok else 'FAIL'} |" for g, n, m, c, ok in R.rows)
    counts = {k: q1(con, f"SELECT COUNT(*) FROM {v}") for k, v in {"Order lines": "ol", "Orders": "od", "Stock movements": "mv", "Purchase orders": "po",
              "PO lines": "pol", "Transfers": "tr", "Shipments (all modes)": "sh", "Freight charge lines": "fc", "Daily on-hand rows": "oh"}.items()}
    car = con.execute("SELECT direction, carrier, COUNT(*) n FROM sh GROUP BY ALL ORDER BY 1, 2").fetchdf()
    txt = [f"# System 1 — Phase 1 Report: Synthetic Universe\n",
           f"Result: **{'ALL CHECKS PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in R.rows)}/{len(R.rows)}). "
           f"Reproducibility tests {'were' if full else 'were NOT'} run in this pass.\n",
           "## Volumes\n", "| Table | Rows |\n|---|---|", *[f"| {k} | {v:,} |" for k, v in counts.items()],
           "\nExternal-feed freight shipments (Carrier A + Carrier B): "
           f"{int(car[car.carrier.isin(['CARRIER_A', 'CARRIER_B'])].n.sum()):,} (spec estimated ~125k; the simulated business ships far less by carrier because own fleet and will-call carry most deliveries).\n",
           "## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (C.ROOT / "docs" / "PHASE1_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def chart(con, ser):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    m = con.execute("""SELECT date_trunc('month', l.order_date) mo, s.category_id c, COUNT(*) n FROM ol l JOIN sku s USING (sku_id)
                       WHERE l.order_date >= DATE '2024-10-01' GROUP BY ALL ORDER BY 1""").fetchdf()
    names = {1: "Lumber", 2: "Roofing", 3: "Insulation", 7: "HVAC"}
    for c, nm in names.items():
        d = m[m.c == c]
        ax[0, 0].plot(d.mo, d.n, label=nm, marker="o", ms=3)
    ax[0, 0].set_title("Seasonality: order lines per month by category")
    ax[0, 0].legend()
    f = con.execute("""SELECT date_trunc('week', order_date) wk, AVG(CASE WHEN line_status = 'filled_same_day' THEN 1.0 ELSE 0.0 END) fr
                       FROM ol WHERE order_date >= DATE '2024-10-01' GROUP BY ALL ORDER BY 1""").fetchdf()
    ax[0, 1].plot(f.wk, f.fr * 100, lw=1)
    ax[0, 1].axvspan(pd.Timestamp(C.S1_START), pd.Timestamp(C.S1_DISCOVERED), alpha=0.15, label="S1 phantom stock (WH-05)")
    ax[0, 1].axvspan(pd.Timestamp(C.S5_START), pd.Timestamp(C.S5_END), alpha=0.15, color="orange", label="S5 roofing surge (WH-04)")
    ax[0, 1].set_ylim(90, 100.5)
    ax[0, 1].set_title("Same-day line fill rate, weekly (%)")
    ax[0, 1].legend(loc="lower left")
    s1 = ser[ser.sc == "S1"]
    s1 = s1[(s1.d >= "2026-01-15") & (s1.d <= "2026-08-15")]
    ax[1, 0].plot(s1.d, s1.onhand, label="true on-hand (85 SKUs)")
    ax[1, 0].plot(s1.d, s1.backlog, label="backordered units")
    ax[1, 0].axvline(pd.Timestamp(C.S1_START), ls="--", c="r")
    ax[1, 0].axvline(pd.Timestamp(C.S1_DISCOVERED), ls="--", c="g")
    ax[1, 0].set_title("S1: Albuquerque phantom stock (red=loss, green=discovered)")
    ax[1, 0].legend()
    s5 = ser[ser.sc == "S5"]
    s5 = s5[(s5.d >= "2026-03-01") & (s5.d <= "2026-09-30")]
    ax[1, 1].plot(s5.d, s5.zero_share * 100)
    ax[1, 1].axvspan(pd.Timestamp(C.S5_START), pd.Timestamp(C.S5_END), alpha=0.15, color="orange")
    ax[1, 1].set_title("S5: Las Vegas roofing SKUs out of stock (% of SKUs)")
    for a in ax.ravel():
        a.tick_params(axis="x", rotation=30)
        a.grid(alpha=0.3)
    fig.suptitle("System 1 synthetic universe: realism and scenario check (all data synthetic)", fontsize=12)
    fig.tight_layout()
    fig.savefig(C.ROOT / "docs" / "phase1_realism.png", dpi=110)


def main():
    full = "--full" in sys.argv
    con = connect()
    R = Results()
    integrity(con, R)
    calibration(con, R)
    realism(con, R)
    ser = scenarios(con, R)
    if full:
        reproducibility(R)
    write_report(R, ser, con, full)
    chart(con, ser)
    print(f"\n{sum(r[4] for r in R.rows)}/{len(R.rows)} checks passed")
    sys.exit(0 if R.all_ok else 1)


if __name__ == "__main__":
    main()
