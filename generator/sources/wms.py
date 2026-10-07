"""WMS source: JSON-lines event stream per warehouse (WH-01..04, WH-06), delivered at-least-once, UTC timestamps.
Defects W1-W6, S3 and the cross-source C3 are injected and logged. WH-05 runs on the legacy system instead.

Two stages: prepare() builds the events the WMS actually records (semantic defects W5, W6, C3 applied);
finish() adds cycle-count adjustments, then delivery behaviour (W1 duplicates, W2 late arrival, S3 outage, W4 bin drift)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as C
from .common import (SRC, W0, E0, H0, DefectLog, Truth, _mix, link_dates, order_no, pick, po_no, u01, ufloat, uint)

SYS = "WMS"
END_UTC = pd.Timestamp(C.HORIZON_END, tz="UTC") + pd.Timedelta(days=1)
WMS_TYPES = {"receipt": ["RECEIVE", "PUTAWAY"], "ship": ["PICK", "PACK", "SHIP"], "transfer_out": ["TRANSFER_OUT"],
             "transfer_in": ["TRANSFER_IN"], "disposal": ["ADJUST"]}
EFFECT = {"RECEIVE": 1, "SHIP": -1, "TRANSFER_OUT": -1, "TRANSFER_IN": 1, "OPENING_BALANCE": 1}
DRIFT_DATE = pd.Timestamp("2026-02-15")


def event_id(keys) -> np.ndarray:
    h = _mix(np.asarray(keys).astype(np.int64).view(np.uint64) ^ np.uint64(0xA5A5A5A5DEADBEEF))
    return np.array([f"{v:016x}" for v in h.tolist()])


def bins_table(T: Truth) -> pd.DataFrame:
    p = T.pairs.merge(T.sku[["sku_id", "category_id"]], on="sku_id")
    k = p.pair_id.values
    aisle = np.array(list("ABCDEFGHIJKL"))[p.category_id.values - 1]
    rack, lvl = uint(k, "rack", 1, 40), uint(k, "lvl", 1, 5)
    return pd.DataFrame({"sku_id": p.sku_id.values, "warehouse_id": p.warehouse_id.values,
                         "bin_old": [f"{a}-{r}-{l}" for a, r, l in zip(aisle, rack, lvl)],
                         "bin_new": [f"{a}{r:02d}-{l:02d}" for a, r, l in zip(aisle, rack, lvl)]})


def c3_plan(T: Truth) -> pd.DataFrame:
    # transfers that straddle the end of history (out on or before it, in after it) are never chosen: their out side was delivered as normal
    tr = T.tr[(T.tr.in_date <= E0) & (T.tr.out_date >= W0) & ((T.tr.in_date <= H0) | (T.tr.out_date > H0))].copy()
    tr = tr[pick(tr.transfer_id.values, "c3", 0.012)].copy()
    tr["drop_side"] = np.where(u01(tr.transfer_id.values, "c3s") < 0.5, "out", "in")
    return tr


def prepare(T: Truth, log: DefectLog) -> pd.DataFrame:
    wms_wh = set(T.wh.warehouse_id[T.wh.wms_covered])
    mv = T.mv[T.mv.warehouse_id.isin(wms_wh) & T.mv.movement_type.isin(WMS_TYPES)].copy()
    sku = T.sku.set_index("sku_id")
    ono = pd.Series(order_no(T.lines.order_id).values, index=T.lines.line_id.values)
    pno = pd.Series(po_no(T.pol.po_id).values, index=T.pol.po_line_id.values)
    mv["ref_no"] = ""
    sh, rc = mv.movement_type == "ship", mv.movement_type == "receipt"
    tx = mv.movement_type.isin(["transfer_out", "transfer_in"])
    mv.loc[sh, "ref_no"] = mv.loc[sh, "ref_id"].map(ono).values
    mv.loc[rc, "ref_no"] = mv.loc[rc, "ref_id"].map(pno).values
    mv.loc[tx, "ref_no"] = "TO-" + mv.loc[tx, "ref_id"].astype(str).str.zfill(6)
    lo = pd.Series(T.lines.order_id.values, index=T.lines.line_id.values)
    mv["order_ts"] = mv.ref_id.where(sh).map(lo).map(T.orders.set_index("order_id").order_ts_utc)

    parts = []
    for mtype, etypes in WMS_TYPES.items():
        m = mv[mv.movement_type == mtype]
        for k, et in enumerate(etypes):
            parts.append(pd.DataFrame({
                "mv_id": m.movement_id.values, "k": k, "etype": et, "wh_id": m.warehouse_id.values, "sku_id": m.sku_id.values,
                "qty": m.qty_delta.abs().values, "ref_no": m.ref_no.values, "mdate": m.movement_date.values, "ts": m.ts_utc.values,
                "order_ts": m.order_ts.values, "line_or_ref": m.ref_id.values, "mtype": mtype}))
    ev = pd.concat(parts, ignore_index=True)
    ev["ts"] = pd.to_datetime(ev.ts, utc=True)
    ev["order_ts"] = pd.to_datetime(ev.order_ts, utc=True)
    ev["eid_key"] = ev.mv_id * 8 + ev.k
    # pick/pack happen between order entry and ship; putaway follows receipt
    t_s = ev.ts
    t_o = pd.concat([ev.order_ts.fillna(ev.ts), ev.ts - pd.Timedelta(hours=6)], axis=1).max(axis=1)
    span = (t_s - t_o).dt.total_seconds()
    frac = np.where(ev.etype == "PICK", ufloat(ev.eid_key.values, "pick", 0.15, 0.45), ufloat(ev.eid_key.values, "pack", 0.5, 0.8))
    is_pp = ev.etype.isin(["PICK", "PACK"])
    ev["ts"] = t_s.where(~is_pp, t_o + pd.to_timedelta(span * frac, unit="s"))
    pa_ = ev.etype == "PUTAWAY"
    ev.loc[pa_, "ts"] = ev.loc[pa_, "ts"] + pd.to_timedelta(uint(ev.eid_key.values[pa_], "putaway", 20, 180), unit="m")
    ev["direction"] = np.select([ev.etype.isin(["RECEIVE", "TRANSFER_IN"]), ev.etype.isin(["SHIP", "TRANSFER_OUT"])], ["IN", "OUT"], "NONE")
    ev["ref_type"] = ev.etype.map({"RECEIVE": "PO", "PUTAWAY": "PO", "PICK": "SO", "PACK": "SO", "SHIP": "SO", "TRANSFER_OUT": "TO", "TRANSFER_IN": "TO", "ADJUST": "ADJ"})
    ev["reason"] = np.where(ev.etype == "ADJUST", "OBSOLETE_WRITEOFF", None)
    ev.loc[ev.etype == "ADJUST", "direction"] = "OUT"
    ev["book_sku"] = ev.sku_id
    ev["src"] = "movement"

    op = T.opening[T.opening.warehouse_id.isin(wms_wh) & (T.opening.onhand_qty > 0)]
    obe = pd.DataFrame({"mv_id": -1 - np.arange(len(op)), "k": 0, "etype": "OPENING_BALANCE", "wh_id": op.warehouse_id.values,
                        "sku_id": op.sku_id.values, "qty": op.onhand_qty.values, "ref_no": "", "mdate": W0 - pd.Timedelta(days=1),
                        "mtype": "opening", "line_or_ref": 0, "eid_key": 10 ** 12 + np.arange(len(op)), "direction": "IN", "ref_type": "OB",
                        "reason": None, "book_sku": op.sku_id.values, "src": "opening"})
    obe["ts"] = pd.to_datetime([pd.Timestamp(C.WINDOW_START).tz_localize(T.wh_tz[w]).tz_convert("UTC") - pd.Timedelta(minutes=5) for w in obe.wh_id])
    obe["order_ts"] = pd.NaT
    ev = pd.concat([ev, obe], ignore_index=True)
    for col in ("sku_id", "book_sku", "wh_id", "qty"):
        ev[col] = ev[col].astype("int64")

    # W5: a receipt keyed under the wrong item (another SKU in the same category and warehouse)
    pairs = T.pairs.merge(T.sku[["sku_id", "category_id"]], on="sku_id")
    cand = {k: np.sort(g.sku_id.values) for k, g in pairs.groupby(["warehouse_id", "category_id"])}
    rcv = ev[(ev.etype == "RECEIVE") & (ev.src == "movement") & pick(ev.eid_key.values, "w5", 0.008)]
    wrong = {}
    for r in rcv.itertuples():
        lst = cand[(r.wh_id, int(sku.loc[r.sku_id, "category_id"]))]
        i = int(uint(np.array([r.eid_key]), "w5s", 0, len(lst) - 1)[0])
        wrong[r.mv_id] = int(lst[i] if lst[i] != r.sku_id else lst[(i + 1) % len(lst)])
    mis = ev.mv_id.isin(wrong.keys()) & ev.etype.isin(["RECEIVE", "PUTAWAY"]) & (ev.src == "movement")
    ev.loc[mis, "book_sku"] = ev.loc[mis, "mv_id"].map(wrong).astype(int).values
    rr = ev[mis & (ev.etype == "RECEIVE")]
    log.add("W5", SYS, "wms_events", event_id(rr.eid_key.values), "movement", rr.mv_id, rr.mdate,
            [{"true_sku_id": int(a), "booked_sku_id": int(b), "qty": int(q)} for a, b, q in zip(rr.sku_id, rr.book_sku, rr.qty)],
            "FLAG (later picks exceed book)")

    # W6: pick and pack recorded, ship confirmation never arrives
    ships = ev[(ev.etype == "SHIP")]
    drop = ships[pick(ships.line_or_ref.values, "w6", 0.005)]
    mode = T.lines[["line_id", "order_id"]].merge(T.orders[["order_id", "delivery_mode"]], on="order_id").set_index("line_id").delivery_mode
    dm = drop.line_or_ref.map(mode)
    log.add("W6", SYS, "wms_events", event_id(drop.eid_key.values), "order_line", drop.line_or_ref, drop.mdate,
            [{"delivery_mode": m, "carrier_evidence": m.startswith("CARRIER")} for m in dm], "FLAG; AUTO-reconcile via carrier evidence")
    ev = ev.drop(index=drop.index)

    # C3: one side of a transfer never reaches its system
    plan = c3_plan(T)
    sysname = np.where(plan.to_warehouse_id == 5, "LEGACY", "WMS")
    sides = np.where(plan.drop_side == "out", "WMS", sysname)
    log.add("C3", "CROSS", "transfers", "TO-" + plan.transfer_id.astype(str).str.zfill(6), "transfer", plan.transfer_id, plan.out_date,
            [{"missing_side": s, "missing_in": sy} for s, sy in zip(plan.drop_side, sides)], "FLAG (in-transit inventory)")
    for side, et in (("out", "TRANSFER_OUT"), ("in", "TRANSFER_IN")):
        refs = "TO-" + plan.transfer_id[plan.drop_side == side].astype(str).str.zfill(6)
        ev = ev.drop(index=ev[(ev.etype == et) & ev.ref_no.isin(refs)].index)
    return ev.reset_index(drop=True)


def book_effects(ev: pd.DataFrame) -> pd.DataFrame:
    """Signed effect of each event on the system's book quantity, credited to the SKU the system believes it is."""
    s = ev.etype.map(EFFECT).fillna(0).astype(int)
    adj = ev.etype == "ADJUST"
    s[adj] = np.where(ev.direction[adj] == "IN", 1, -1)
    return pd.DataFrame({"sku_id": ev.book_sku.values, "wh_id": ev.wh_id.values, "mdate": ev.mdate.values, "eff": (s * ev.qty).values})


def finish(T: Truth, ev: pd.DataFrame, log: DefectLog) -> dict:
    ev = ev.copy().reset_index(drop=True)
    key = ev.eid_key.values
    ev["event_id"] = event_id(key)
    norm = ev.src != "opening"
    wh_code = ev.wh_id.map(T.wh_code)
    # publication time: normal sub-15-minute lag, W2 late arrivals, S3 outage burst
    lag = pd.to_timedelta(ufloat(key, "lag", 5, 900), unit="s")
    late = norm.values & pick(key, "w2", 0.025)
    lag = lag + pd.to_timedelta(np.where(late, uint(key, "w2l", 6 * 3600, 72 * 3600), 0), unit="s")
    pub = ev.ts + lag
    tz3 = T.wh_tz[C.S3_WH]
    s3a = pd.Timestamp(C.S3_START).tz_localize(tz3).tz_convert("UTC")
    s3b = (pd.Timestamp(C.S3_END) + pd.Timedelta(days=1)).tz_localize(tz3).tz_convert("UTC")
    in_out = (ev.wh_id == C.S3_WH).values & (ev.ts >= s3a).values & (ev.ts < s3b).values
    burst = ev.ts + pd.to_timedelta(ufloat(key, "s3d", 36 * 3600, 60 * 3600), unit="s")
    burst = pd.concat([burst, pd.Series(s3b, index=ev.index) + pd.to_timedelta(ufloat(key, "s3e", 0, 6 * 3600), unit="s")], axis=1).max(axis=1)
    pub = pub.where(~in_out, burst)
    blocked = (ev.wh_id == C.S3_WH).values & (pub >= s3a).values & (pub < s3b).values & ~in_out
    pub = pub.where(~blocked, pd.Series(s3b, index=ev.index) + pd.to_timedelta(ufloat(key, "s3f", 0, 6 * 3600), unit="s"))
    # L1 (live future): a second outage, at Tucson, with the same mechanics under its own random salts
    tz1 = T.wh_tz[C.L1_WH]
    l1a = pd.Timestamp(C.L1_START).tz_localize(tz1).tz_convert("UTC")
    l1b = (pd.Timestamp(C.L1_END) + pd.Timedelta(days=1)).tz_localize(tz1).tz_convert("UTC")
    l1_out = (ev.wh_id == C.L1_WH).values & (ev.ts >= l1a).values & (ev.ts < l1b).values
    burst1 = ev.ts + pd.to_timedelta(ufloat(key, "l1d", 36 * 3600, 60 * 3600), unit="s")
    burst1 = pd.concat([burst1, pd.Series(l1b, index=ev.index) + pd.to_timedelta(ufloat(key, "l1e", 0, 6 * 3600), unit="s")], axis=1).max(axis=1)
    pub = pub.where(~l1_out, burst1)
    blocked1 = (ev.wh_id == C.L1_WH).values & (pub >= l1a).values & (pub < l1b).values & ~l1_out
    pub = pub.where(~blocked1, pd.Series(l1b, index=ev.index) + pd.to_timedelta(ufloat(key, "l1f", 0, 6 * 3600), unit="s"))
    ev["pub"] = pub
    log.add("W2", SYS, "wms_events", ev.event_id[late], "movement", ev.mv_id[late], ev.mdate[late],
            [{"delay_h": round(d, 1)} for d in ((pub - ev.ts).dt.total_seconds() / 3600)[late]], "AUTO (event-time ordering)")
    log.add("S3", SYS, "wms_events", ev.event_id[in_out], "movement", ev.mv_id[in_out], ev.mdate[in_out],
            [{"delay_h": round(d, 1)} for d in ((pub - ev.ts).dt.total_seconds() / 3600)[in_out]], "AUTO (backfill; mark gap while open)")
    log.add("L1", SYS, "wms_events", ev.event_id[l1_out], "movement", ev.mv_id[l1_out], ev.mdate[l1_out],
            [{"delay_h": round(d, 1)} for d in ((pub - ev.ts).dt.total_seconds() / 3600)[l1_out]], "AUTO (backfill; mark gap while open)")
    # W3 (natural): events for items the ERP has not yet linked to a WMS item id
    link = link_dates(T)
    sk_link = ev.book_sku.map(link)
    local_date = ev.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    unlinked = (sk_link.notna() & (local_date < sk_link)).values & norm.values
    log.add("W3", SYS, "wms_events", ev.event_id[unlinked], "movement", ev.mv_id[unlinked], ev.mdate[unlinked],
            [{"linked_on": str(d.date())} for d in sk_link[unlinked]], "QUARANTINE (auto-release when linked)")
    # W1: at-least-once delivery duplicates
    dup = norm.values & pick(key, "w1", 0.018)
    d = ev[dup].copy()
    d["pub"] = d.pub + pd.to_timedelta(ufloat(d.eid_key.values, "w1d", 60, 6 * 3600), unit="s")
    log.add("W1", SYS, "wms_events", d.event_id, "movement", d.mv_id, d.mdate, "", "DEDUPE")
    out = pd.concat([ev, d], ignore_index=True)
    out = out[out.pub < END_UTC].copy()
    # item id, bin (W4 drift at WH-02), operator
    bins = bins_table(T).set_index(["sku_id", "warehouse_id"])
    bk = pd.MultiIndex.from_arrays([out.book_sku.values, out.wh_id.values])
    b_old, b_new = bins.bin_old.reindex(bk).values, bins.bin_new.reindex(bk).values
    drift = (out.wh_id == 2).values & (out.ts.dt.tz_localize(None) >= DRIFT_DATE).values
    drift2 = (out.wh_id == C.L2_WH).values & (out.ts.dt.tz_localize(None) >= pd.Timestamp(C.L2_DATE)).values  # L2 (live future): Las Vegas relabels its bins
    out["bin"] = np.where(drift | drift2, b_new, b_old)
    n_drift = int(((out.wh_id == 2) & drift).sum())
    log.add("W4", SYS, "wms_events", "WH-02 events from 2026-02-15", "format_drift", "", DRIFT_DATE, {"n_events": n_drift},
            "AUTO (versioned bin mapping)")
    if drift2.any():
        log.add("L2", SYS, "wms_events", f"WH-04 events from {C.L2_DATE}", "format_drift", "", pd.Timestamp(C.L2_DATE), {"n_events": int(drift2.sum())}, "AUTO (versioned bin mapping)")
    items = T.sku.set_index("sku_id").wms_item_id
    rec = pd.DataFrame({
        "event_id": out.event_id.values, "warehouse": out.wh_id.map(T.wh_code).values, "event_type": out.etype.values,
        "event_ts": out.ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ").values, "published_at": out.pub.dt.strftime("%Y-%m-%dT%H:%M:%SZ").values,
        "item_id": out.book_sku.map(items).values, "quantity": out.qty.astype(int).values, "direction": out.direction.values, "uom": "EA",
        "bin": out.bin.values, "ref_type": out.ref_type.values, "ref_no": out.ref_no.values,
        "operator": [f"OP{w:02d}{n:02d}" for w, n in zip(out.wh_id, uint(out.eid_key.values, "op", 1, 12))],
        "reason": out.reason.values, "schema_version": 1})
    rec["_wh"] = rec.warehouse
    rec["_d"] = out.pub.dt.strftime("%Y-%m-%d").values
    rec["_batch"] = rec.warehouse + "-" + out.pub.dt.strftime("%Y%m%d-%H").values
    rec["batch_id"] = rec._batch
    rec = rec.sort_values(["_wh", "published_at", "event_id"])
    n_files = 0
    for (wh, day), g in rec.groupby(["_wh", "_d"], sort=True):
        folder = SRC / "wms" / wh
        folder.mkdir(parents=True, exist_ok=True)
        g.drop(columns=["_wh", "_d", "_batch"]).to_json(folder / f"{day}.jsonl", orient="records", lines=True, force_ascii=False)
        n_files += 1
    return {"wms_events_written": len(rec), "wms_files": n_files, "w1_dups": int(dup.sum()), "w2_late": int(late.sum()),
            "s3_events": int(in_out.sum()), "w3_unlinked": int(unlinked.sum()), "w4_drift_events": n_drift,
            "in_flight_excluded": int(len(ev) + len(d) - len(out))}
