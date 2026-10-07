"""Run the 24-month history and write the truth store (Parquet) to truth/.  Usage: python -m generator.run_history"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import config as C
from .simulate import CARRIERS, EPOCH_ORD, MOVE_TYPES, REF_TYPES, Sim

W = C.WINDOW_START.toordinal()


def _d(ords, null=None):
    a = (np.asarray(ords, dtype=np.int64) - EPOCH_ORD).astype(np.int32)
    return pa.array(a, type=pa.int32(), mask=null).cast(pa.date32())


def _ts(sec):
    return pa.array(np.asarray(sec, dtype=np.int64)).cast(pa.timestamp("s", tz="UTC"))


def _str(idx, names):
    return pa.array(np.array(names)[np.asarray(idx)])


def table_hash(t: pa.Table) -> str:
    h = hashlib.sha256()
    for name in t.column_names:
        col = t.column(name).combine_chunks()
        h.update(name.encode())
        if pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
            h.update("|".join(map(str, col.to_pylist())).encode())
        else:
            h.update(np.ascontiguousarray(col.to_numpy(zero_copy_only=False)).tobytes())
    return h.hexdigest()[:16]


def build_tables(sim: Sim) -> dict[str, pa.Table]:
    M, r = sim.M, sim.rec
    T: dict[str, pa.Table] = {}
    ship_i = MOVE_TYPES.index("ship")

    mv_all = r.frame("move")
    mv = mv_all[mv_all.date_ord >= W]
    T["truth_movements"] = pa.table({
        "movement_id": mv.movement_id.values, "movement_date": _d(mv.date_ord), "ts_utc": _ts(mv.ts_utc),
        "sku_id": (mv.sku_idx + 1).astype("int32").values, "warehouse_id": (mv.wh_idx + 1).astype("int8").values,
        "qty_delta": mv.qty.astype("int32").values, "movement_type": _str(mv.mtype, MOVE_TYPES),
        "ref_type": _str(mv.ref_type, REF_TYPES), "ref_id": mv.ref_id.values})

    # orders and lines: keep anything dated in the window or still moving stock in it
    ln, od = r.frame("line"), r.frame("order")
    mv_ship = mv_all[mv_all.mtype == ship_i].assign(q=lambda d: -d.qty)
    agg = mv_ship.groupby("ref_id").agg(qty_shipped=("q", "sum"), first_ship=("date_ord", "min"), last_ship=("date_ord", "max"))
    live_lines = set(mv_ship[mv_ship.date_ord >= W].ref_id.unique())
    ln = ln[(ln.date_ord >= W) | ln.line_id.isin(live_lines)].merge(agg, left_on="line_id", right_index=True, how="left")
    ln["qty_shipped"] = ln.qty_shipped.fillna(0).astype(int)
    status = np.where(ln.qty_shipped < ln.qty_ordered, "open_backorder",
                      np.where((ln.first_ship == ln.date_ord) & (ln.last_ship == ln.date_ord), "filled_same_day", "backordered_filled"))
    od = od[od.order_id.isin(ln.order_id.unique())]
    nl = ln.groupby("order_id").size()
    T["truth_order_lines"] = pa.table({
        "line_id": ln.line_id.values, "order_id": ln.order_id.values, "line_no": ln.line_no.astype("int16").values,
        "sku_id": (ln.sku_idx + 1).astype("int32").values, "qty_ordered": ln.qty_ordered.astype("int32").values,
        "unit_price": ln.unit_price.values, "order_date": _d(ln.date_ord), "qty_shipped": ln.qty_shipped.astype("int32").values,
        "first_ship_date": _d(ln.first_ship.fillna(0), null=ln.first_ship.isna().values),
        "last_ship_date": _d(ln.last_ship.fillna(0), null=ln.last_ship.isna().values), "line_status": pa.array(status)})
    T["truth_orders"] = pa.table({
        "order_id": od.order_id.values, "customer_id": (od.customer_idx + 1).astype("int32").values,
        "warehouse_id": (od.wh_idx + 1).astype("int8").values, "order_date": _d(od.date_ord), "order_ts_utc": _ts(od.ts_utc),
        "delivery_mode": _str(od.delivery_mode, CARRIERS), "order_weight_lb": od.weight_lb.values,
        "n_lines": nl.reindex(od.order_id).values.astype("int16")})

    # purchasing
    po, pl = r.frame("po"), r.frame("po_line")
    po = po[po.received_ord >= W]
    pl = pl[pl.po_id.isin(po.po_id)]
    T["truth_purchase_orders"] = pa.table({
        "po_id": po.po_id.values, "vendor_id": (po.vendor_idx + 1).astype("int32").values,
        "warehouse_id": (po.wh_idx + 1).astype("int8").values, "po_date": _d(po.po_ord), "promised_date": _d(po.promised_ord),
        "received_date": _d(po.received_ord)})
    T["truth_po_lines"] = pa.table({
        "po_line_id": pl.po_line_id.values, "po_id": pl.po_id.values, "sku_id": (pl.sku_idx + 1).astype("int32").values,
        "qty_ordered": pl.qty_ordered.astype("int32").values, "qty_received": pl.qty_received.astype("int32").values,
        "unit_cost": pl.unit_cost.values, "received_date": _d(pl.received_ord)})
    tr = r.frame("transfer")
    tr = tr[(tr.out_ord >= W) | (tr.in_ord >= W)]
    T["truth_transfers"] = pa.table({
        "transfer_id": tr.transfer_id.values, "sku_id": (tr.sku_idx + 1).astype("int32").values,
        "from_warehouse_id": (tr.from_wh_idx + 1).astype("int8").values, "to_warehouse_id": (tr.to_wh_idx + 1).astype("int8").values,
        "qty": tr.qty.astype("int32").values, "out_date": _d(tr.out_ord), "in_date": _d(tr.in_ord)})

    # freight
    sh, ch = r.frame("ship"), r.frame("charge")
    sh = sh[(sh.ship_ord >= W) | (sh.delivered_ord >= W)]
    ch = ch[ch.shipment_id.isin(sh.shipment_id)]
    T["truth_shipments"] = pa.table({
        "shipment_id": sh.shipment_id.values, "direction": _str(sh.direction, ["outbound", "inbound"]),
        "carrier": _str(sh.carrier, CARRIERS), "ref_type": _str(sh.ref_type, ["order", "po"]), "ref_id": sh.ref_id.values,
        "warehouse_id": (sh.wh_idx + 1).astype("int8").values, "ship_date": _d(sh.ship_ord), "ship_ts_utc": _ts(sh.ship_ts),
        "weight_lb": sh.weight_lb.values, "pieces": sh.pieces.astype("int32").values, "miles": sh.miles.values,
        "quoted_transit_days": sh.quoted_transit_days.astype("int16").values, "promised_delivery_date": _d(sh.promised_ord),
        "actual_delivery_date": _d(sh.delivered_ord)})
    T["truth_freight_charges"] = pa.table({
        "charge_id": ch.charge_id.values, "shipment_id": ch.shipment_id.values, "charge_type": pa.array(ch.charge_type.values.astype(str)),
        "amount": ch.amount.values})

    # inventory truth: daily snapshot (long) + opening balance
    ords = np.concatenate(r.t["snap"]["date_ord"])
    oh, bl, oo = (np.vstack(r.t["snap"][k]) for k in ("onhand", "backlog", "on_order"))
    nd, P = oh.shape
    T["truth_onhand_daily"] = pa.table({
        "snapshot_date": _d(np.repeat(ords, P)), "sku_id": np.tile((M.pair_sku + 1).astype("int32"), nd),
        "warehouse_id": np.tile((M.pair_wh + 1).astype("int8"), nd), "onhand_qty": oh.ravel(), "backlog_qty": bl.ravel(),
        "on_order_qty": oo.ravel()})
    op = np.vstack(r.t["opening"]["onhand"])[0]
    T["truth_opening_balance"] = pa.table({
        "as_of_date": _d(np.full(P, W - 1)), "sku_id": (M.pair_sku + 1).astype("int32"), "warehouse_id": (M.pair_wh + 1).astype("int8"),
        "onhand_qty": op})

    T.update(build_dims(sim))
    return T


def build_dims(sim: Sim) -> dict[str, pa.Table]:
    M = sim.M
    n = M.n_sku
    T = {}
    T["dim_warehouse"] = pa.Table.from_pandas(pd.DataFrame({
        "warehouse_id": M.wh_id, "warehouse_code": M.wh_code, "name": M.wh_name, "city": M.wh_city, "timezone": M.wh_tz,
        "is_hub": M.wh_is_hub, "wms_covered": M.wh_wms, "volume_share": M.wh_share}), preserve_index=False)
    T["dim_category"] = pa.Table.from_pandas(pd.DataFrame({"category_id": np.arange(1, M.n_cat + 1), "name": M.cat_name}), preserve_index=False)
    succ = M.sku_successor
    intro_null = M.sku_intro < -10 ** 5
    disc_null = M.sku_disc > 10 ** 8
    T["dim_sku"] = pa.table({
        "sku_id": np.arange(1, n + 1, dtype="int32"), "sku_code": pa.array(M.sku_code), "legacy_code": pa.array(M.sku_legacy_code),
        "wms_item_id": M.sku_wms_item_id.astype("int64"), "description": pa.array(M.sku_desc),
        "category_id": (M.sku_cat + 1).astype("int8"), "vendor_id": (M.sku_vendor + 1).astype("int32"),
        "lifecycle_kind": pa.array(M.sku_kind.astype(str)), "abc_class": pa.array(M.sku_class.astype(str)),
        "intro_date": _d(np.where(intro_null, 0, M.sku_intro), null=intro_null),
        "discontinue_date": _d(np.where(disc_null, 0, M.sku_disc), null=disc_null),
        "successor_sku_id": pa.array(np.where(succ >= 0, succ + 1, 0).astype("int32"), mask=succ < 0),
        "list_price": np.round(M.sku_price0 * sim.price_scale, 2), "unit_cost": np.round(M.sku_cost0 * sim.price_scale, 2),
        "weight_lb": np.round(M.sku_weight, 2), "case_pack_qty": M.sku_case_pack.astype("int32"), "base_uom": pa.array(["EA"] * n),
        "mean_line_qty": np.round(M.sku_mean_qty, 1)})
    T["dim_sku_warehouse"] = pa.table({
        "pair_id": np.arange(1, M.n_pair + 1, dtype="int32"), "sku_id": (M.pair_sku + 1).astype("int32"),
        "warehouse_id": (M.pair_wh + 1).astype("int8")})
    primary = pd.DataFrame({"v": M.sku_vendor, "c": M.sku_cat}).groupby("v").c.agg(lambda x: x.value_counts().index[0])
    words = [n.split(" ")[0].replace("&", "").strip() for n in M.cat_name]
    vnames, used = [], set()
    for v, nm in enumerate(M.vend_name):
        parts = nm.split(" ")
        base = f"{parts[0]} {words[int(primary.get(v, 0))]} {parts[-1]}"
        cand, k = base, 2
        while cand in used:
            cand, k = f"{base} {k}", k + 1
        used.add(cand)
        vnames.append(cand)
    T["dim_vendor"] = pa.Table.from_pandas(pd.DataFrame({
        "vendor_id": np.arange(1, M.n_vend + 1), "name": vnames, "is_import": M.vend_import,
        "quoted_lead_time_days": M.vend_quoted_lt, "late_delivery_probability": np.round(M.vend_late_prob, 3),
        "distance_miles": np.round(M.vend_dist_miles, 0), "buy_cycle_weeks": M.vend_cycle,
        "order_weekdays": [",".join("MTWRF"[d] for d in ds) for ds in M.vend_order_days]}), preserve_index=False)
    cs, ce = M.cust_start, M.cust_end
    T["dim_customer"] = pa.table({
        "customer_id": np.arange(1, M.n_cust + 1, dtype="int32"), "name": pa.array(M.cust_name),
        "customer_type": pa.array(np.array(C.CUSTOMER_TYPES)[M.cust_type]), "ship_to_city": pa.array(M.cust_city),
        "default_warehouse_id": (M.cust_wh + 1).astype("int8"), "distance_miles": np.round(M.cust_dist_miles, 1),
        "discount_pct": M.cust_discount, "payment_terms": pa.array(M.cust_terms.astype(str)),
        "active_from": _d(np.where(cs < -10 ** 5, 0, cs), null=cs < -10 ** 5), "active_to": _d(np.where(ce > 10 ** 8, 0, ce), null=ce > 10 ** 8)})
    T["dim_carrier"] = pa.Table.from_pandas(pd.DataFrame({
        "carrier_code": CARRIERS, "name": ["Carrier A (LTL freight)", "Carrier B (parcel)", "Own fleet", "Customer will-call",
                                          "Vendor-delivered", "Own pickup at vendor"],
        "is_external_feed": [True, True, False, False, False, False]}), preserve_index=False)
    cal = M.cal
    m = np.array([d >= C.WARMUP_START for d in cal.dates])
    T["dim_calendar"] = pa.table({
        "date": _d(cal.ordinals[m]), "day_of_week": cal.dow[m].astype("int8"), "is_holiday": cal.is_hol[m],
        "holiday_name": pa.array(np.array(cal.holiday_name)[m]), "is_open_day": cal.is_open[m], "is_receiving_day": cal.is_recv[m],
        "price_index": np.round(cal.price_index[m], 5)})
    # scenarios
    rows = [
        ("S1", "Phantom stock, Albuquerque", C.S1_START, C.S1_DISCOVERED, 5,
         "Physical stock for the listed SKUs at WH-05 was lost on the start date and never adjusted in the legacy system; "
         "replenishment stopped (the book showed stock) until a count found it on the end date.", json.dumps({"n_skus": C.S1_N_SKUS})),
        ("S2", "Carrier B schema change", C.S2_DATE, C.S2_DATE, 0,
         "Source-level (Phase 2): weight_lb becomes wt_lbs, service splits into two fields, dim_weight column appears.", "{}"),
        ("S3", "WMS outage, Flagstaff", C.S3_START, C.S3_END, C.S3_WH,
         "Source-level (Phase 2): no WH-03 WMS events for 48h, then a late out-of-order burst 36-60h later.", "{}"),
        ("S4", "Double-billed freight", C.WINDOW_START, C.HISTORY_END, 0,
         "Source-level (Phase 2): Carrier A bills a duplicate of an existing charge line on ~1% of its shipments.", json.dumps({"rate_per_carrier_a_shipment": C.S4_DUPLICATE_BILLING_RATE})),
        ("S5", "Roofing demand surge, Las Vegas", C.S5_START, C.S5_END, C.S5_WH,
         "Demand for the listed roofing SKUs at WH-04 runs at a multiple of normal; the trailing-average planner lags the surge.",
         json.dumps({"multiplier": C.S5_MULT, "n_skus": C.S5_N_SKUS})),
        ("L1", "WMS outage, Tucson (live future)", C.L1_START, C.L1_END, C.L1_WH,
         "Source-level, after the end of history: no WH-02 WMS events for 72h, then a late out-of-order burst 36-60h later.", "{}"),
        ("L2", "Bin relabel, Las Vegas (live future)", C.L2_DATE, C.L2_DATE, C.L2_WH,
         "Source-level, after the end of history: WH-04 starts publishing bins as A12-03 instead of A-12-3.", "{}")]
    rows = [r for r in rows if not (r[0] in ("L1", "L2") and C.HORIZON_END < r[2])]  # live-future incidents exist only when the horizon reaches them
    T["truth_scenarios"] = pa.Table.from_pandas(pd.DataFrame(rows, columns=["scenario_id", "name", "start_date", "end_date", "warehouse_id",
                                                                           "truth_description", "parameters_json"]), preserve_index=False)
    ent = [("S1", int(M.pair_sku[p]) + 1, int(M.pair_wh[p]) + 1) for p in M.s1_pairs] + \
          [("S5", int(M.pair_sku[p]) + 1, int(M.pair_wh[p]) + 1) for p in M.s5_pairs]
    T["truth_scenario_entities"] = pa.Table.from_pandas(pd.DataFrame(ent, columns=["scenario_id", "sku_id", "warehouse_id"]), preserve_index=False)
    return T


def main():
    t0 = time.time()
    C.TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    sim = Sim()
    sim.run(C.WARMUP_START, C.HORIZON_END)
    print(f"simulated in {time.time() - t0:.0f}s")
    T = build_tables(sim)
    hashes = {}
    for name, t in T.items():
        pq.write_table(t, C.TRUTH_DIR / f"{name}.parquet", compression="zstd")
        hashes[name] = table_hash(t)
        print(f"  {name:28s} {t.num_rows:>10,} rows")
    sim.save_state(C.TRUTH_DIR / "state_end_of_history.pkl")
    meta = {"seed": C.SEED, "window_start": str(C.WINDOW_START), "history_end": str(C.HISTORY_END), "horizon_end": str(C.HORIZON_END), "price_scale": sim.price_scale,
            "line_scale": sim.line_scale, "rows": {k: t.num_rows for k, t in T.items()}, "hashes": hashes}
    (C.TRUTH_DIR / "truth_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
