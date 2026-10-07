"""Freight sources. Carrier A (LTL): daily JSON, shipments with nested tracking events and charges, epoch-millisecond timestamps.
Carrier B (parcel): daily CSVs (shipments, tracking, charges), local time with a text UTC offset.
Defects F1, F2, F4, F5, F7 and scenarios S2 (schema change) and S4 (duplicate billing) are injected and logged."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .. import config as C
from .common import (SRC, W0, E0, H0, DefectLog, Truth, order_no, pick, po_no, u01, uint, ufloat, vendor_city)

SYS = "FREIGHT"
CODE_A = {"linehaul": "LH", "fuel_surcharge": "FSC", "liftgate": "LFT", "residential": "RES", "limited_access": "LTD", "detention": "DET"}
CODE_B = {"base": "BASE", "fuel_surcharge": "FUEL", "residential": "RESI", "oversize": "OVS"}
HUBS = ["Salt Lake City Hub", "Dallas Hub", "Albuquerque Hub", "Barstow Hub", "Denver Hub", "Amarillo Hub"]
S2 = pd.Timestamp(C.S2_DATE)


def _local_to_utc(naive: pd.Series, tz: pd.Series) -> pd.Series:
    out = pd.Series(pd.NaT, index=naive.index, dtype="datetime64[ns, UTC]")
    for z in tz.unique():
        m = (tz == z).values
        out.loc[m] = naive[m].dt.tz_localize(z, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    return out


def shipments_frame(T: Truth) -> pd.DataFrame:
    s = T.ship[T.ship.carrier.isin(["CARRIER_A", "CARRIER_B"])].copy()
    wh = T.wh.set_index("warehouse_id")
    cust = T.cust.set_index("customer_id")
    od = T.orders.set_index("order_id")
    out = s.direction == "outbound"
    s["ref"] = np.where(out, order_no(s.ref_id).values, po_no(s.ref_id).values)
    vc = vendor_city(T)
    po_v = T.po.set_index("po_id").vendor_id
    cust_of = s.ref_id.map(od.customer_id)
    s["origin"] = np.where(out, s.warehouse_id.map(wh.city), s.ref_id.map(po_v).map(vc))
    s["dest"] = np.where(out, cust_of.map(cust.ship_to_city), s.warehouse_id.map(wh.city))
    dest_wh = cust_of.map(cust.default_warehouse_id).fillna(s.warehouse_id)
    s["dest_tz"] = np.where(out, dest_wh.map(wh.timezone), s.warehouse_id.map(wh.timezone))
    s["orig_tz"] = np.where(out, s.warehouse_id.map(wh.timezone), "America/Chicago")
    return s.reset_index(drop=True)


def events_frame(s: pd.DataFrame, log: DefectLog) -> pd.DataFrame:
    k = s.shipment_id.values
    pick_ts = s.ship_ts_utc
    d = pd.to_datetime(s.actual_delivery_date)
    hour = ufloat(k, "dh", 9, 17)
    deliv_local = d + pd.to_timedelta(hour, unit="h")
    deliv = _local_to_utc(deliv_local, s.dest_tz)
    deliv = pd.concat([deliv, pick_ts + pd.to_timedelta(ufloat(k, "dmin", 2, 6), unit="h")], axis=1).max(axis=1)
    # F4: delivery before pickup, or an impossible transit time
    f4 = pick(k, "f4", 0.002)
    kind = u01(k, "f4k") < 0.5
    deliv = deliv.where(~f4, np.where(kind, pick_ts - pd.to_timedelta(ufloat(k, "f4a", 2, 30), unit="h"), pick_ts + pd.to_timedelta(ufloat(k, "f4b", 20, 40), unit="D")))
    log.add("F4", SYS, "shipment", s.ref[f4], "shipment", s.shipment_id[f4], s.ship_date[f4],
            [{"mode": "delivered_before_pickup" if kd else "impossible_transit_days", "true_delivery": str(t)} for kd, t in zip(kind[f4], s.actual_delivery_date[f4])],
            "QUARANTINE")
    isA = (s.carrier == "CARRIER_A").values
    rows = []

    def add(mask, status, ts, loc):
        if mask.any():
            rows.append(pd.DataFrame({"shipment_id": k[mask], "status": status if isinstance(status, str) else status[mask], "ts": ts[mask].values if hasattr(ts, "values") else ts[mask],
                                      "loc": loc[mask]}))
    origin, dest = s.origin.values, s.dest.values
    add(isA, "PICKUP", pick_ts, origin)
    add(isA, "DEPARTED_ORIGIN", pick_ts + pd.to_timedelta(ufloat(k, "dep", 3, 9), unit="h"), origin)
    add(~isA, "LABEL_CREATED", pick_ts - pd.to_timedelta(ufloat(k, "lbl", 1, 4), unit="h"), origin)
    add(~isA, "PICKED_UP", pick_ts, origin)
    days = (d - pd.to_datetime(s.ship_date)).dt.days.values
    n_mid = np.clip(days - 1, 0, 3)
    hubs = np.array(HUBS)
    for j in range(1, 4):
        m = n_mid >= j
        t = pick_ts + pd.to_timedelta(24 * j * np.ones(len(s)) + ufloat(k, f"mid{j}", -4, 4), unit="h")
        add(m, "IN_TRANSIT", t, hubs[uint(k + j, "hub", 0, len(HUBS) - 1)])
    ofd_local = d + pd.Timedelta(hours=7)
    ofd = _local_to_utc(ofd_local, s.dest_tz)
    add(days >= 1, "OUT_FOR_DELIVERY", ofd, dest)
    add(np.ones(len(s), dtype=bool), "DELIVERED", deliv, dest)
    ev = pd.concat(rows, ignore_index=True)
    ev["ts"] = pd.to_datetime(ev.ts, utc=True)
    return ev.sort_values(["shipment_id", "ts"]).reset_index(drop=True)


def mangle(refs: pd.Series, k, log: DefectLog, ship_ids, dates) -> pd.Series:
    m = pick(k, "f2", 0.015)
    kind = u01(k, "f2k")
    r = refs.copy()
    for i in np.nonzero(m)[0]:
        v = refs.iat[i]
        kk = kind[i]
        if kk < 0.25:
            new = v.lower()
        elif kk < 0.45:
            new = v.replace("-", "")
        elif kk < 0.65:
            new = v + " "
        elif kk < 0.75:
            new = v.replace("-", "-0")
        else:  # a keyed digit error: only recoverable with extra evidence
            pos = len(v) - 1 - int(uint(np.array([k[i]]), "f2p", 0, 2)[0])
            new = v[:pos] + str((int(v[pos]) + 3) % 10) + v[pos + 1:]
        r.iat[i] = new
    kinds = np.where(kind < 0.25, "case", np.where(kind < 0.45, "hyphen_dropped", np.where(kind < 0.65, "trailing_space", np.where(kind < 0.75, "zero_padded", "digit_error"))))
    log.add("F2", SYS, "shipment", r[m].values, "shipment", ship_ids[m], dates[m],
            [{"true_ref": a, "written": b, "kind": kd} for a, b, kd in zip(refs[m], r[m], kinds[m])], "AUTO via normalization; digit errors to REVIEW")
    return r


def build(T: Truth, log: DefectLog) -> dict:
    s = shipments_frame(T)
    k = s.shipment_id.values
    isA = (s.carrier == "CARRIER_A").values
    ev = events_frame(s, log)
    s["ref_w"] = mangle(s.ref, k, log, s.shipment_id.values, s.ship_date.values)
    f5 = pick(k, "f5", 0.03)
    which = uint(k, "f5w", 0, 2)
    s["w_weight"] = s.weight_lb.where(~(f5 & (which != 1)))
    s["w_pieces"] = s.pieces.astype("float").where(~(f5 & (which != 0)))
    log.add("F5", SYS, "shipment", s.ref_w[f5], "shipment", s.shipment_id[f5], s.ship_date[f5],
            [{"missing": ["weight", "pieces", "both"][w], "true_weight": float(a), "true_pieces": int(b)} for w, a, b in zip(which[f5], s.weight_lb[f5], s.pieces[f5])],
            "FLAG; cost allocation uses imputed value")
    ch = T.chg.merge(s[["shipment_id", "carrier"]], on="shipment_id")
    stats = {"carrier_shipments": len(s), "carrier_a": int(isA.sum()), "carrier_b": int((~isA).sum())}
    stats.update(_carrier_a(T, s, ev, ch[ch.carrier == "CARRIER_A"], log))
    stats.update(_carrier_b(T, s, ev, ch[ch.carrier == "CARRIER_B"], log))
    return stats


def _carrier_a(T, s, ev, ch, log) -> dict:
    d = SRC / "freight" / "carrier_a"
    d.mkdir(parents=True, exist_ok=True)
    sa = s[s.carrier == "CARRIER_A"].set_index("shipment_id")
    eva = ev[ev.shipment_id.isin(sa.index)].copy()
    eva["fdate"] = eva.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    eva = eva[(eva.fdate >= W0) & (eva.fdate <= E0)]
    # charges: truth lines + F7 duplicates (S4)
    ch = ch.sort_values(["shipment_id", "charge_id"]).copy()
    ch["code"] = ch.charge_type.map(CODE_A)
    ch["line_id"] = ch.shipment_id.map(lambda x: f"B{700000000 + x}") + "-" + (ch.groupby("shipment_id").cumcount() + 1).astype(str)
    sid = sa.index.values
    dupship = sid[pick(sid, "f7", C.S4_DUPLICATE_BILLING_RATE)]
    dups = []
    for sh in dupship:
        g = ch[ch.shipment_id == sh]
        if g.empty:
            continue
        lh = u01(np.array([sh]), "f7l")[0] < 0.10
        src = g[g.code == "LH"].iloc[0] if (lh and (g.code == "LH").any()) else g[g.code != "LH"].iloc[int(uint(np.array([sh]), "f7i", 0, max((g.code != "LH").sum() - 1, 0))[0])] if (g.code != "LH").any() else g.iloc[0]
        dups.append({"shipment_id": sh, "code": src.code, "amount": src.amount, "orig_line": src.line_id, "n": len(g) + 1})
    dd = pd.DataFrame(dups)
    if len(dd):
        dd["line_id"] = [f"B{700000000 + a}-{n}" for a, n in zip(dd.shipment_id, dd.n)]
        log.add("F7", SYS, "charge_line", dd.line_id, "shipment", dd.shipment_id, sa.ship_date.reindex(dd.shipment_id).values,
                [{"duplicates_line": o, "code": c, "amount": float(a)} for o, c, a in zip(dd.orig_line, dd.code, dd.amount)], "FLAG for dispute (recoverable)")
        ch2 = pd.concat([ch[["shipment_id", "code", "amount", "line_id"]], dd[["shipment_id", "code", "amount", "line_id"]]], ignore_index=True)
    else:
        ch2 = ch[["shipment_id", "code", "amount", "line_id"]]
    charges = {sid_: g[["line_id", "code", "amount"]].to_dict("records") for sid_, g in ch2.groupby("shipment_id")}
    # per-shipment static record and event lists
    evl = {sid_: g for sid_, g in eva.groupby("shipment_id")}
    # delivery date (UTC) decides when the invoice charges appear
    deliv = eva[eva.status == "DELIVERED"].set_index("shipment_id").fdate
    files: dict = {}
    for sh, g in evl.items():
        r = sa.loc[sh]
        g = g.sort_values("ts")
        for fd in g.fdate.unique():
            sub = g[g.fdate <= fd]
            evs = [{"ts_ms": int(t.value // 10 ** 6), "status": st, "location": lo} for t, st, lo in zip(sub.ts, sub.status, sub["loc"])]
            rec = {"bol_no": f"BOL{700000000 + sh}", "pro_no": f"{800000000 + sh}", "shipper_ref": r.ref_w, "service": "LTL-STD",
                   "origin": {"city": r.origin}, "destination": {"city": r.dest}, "pieces": None if pd.isna(r.w_pieces) else int(r.w_pieces),
                   "weight_lb": None if pd.isna(r.w_weight) else float(r.w_weight), "status": sub.status.iloc[-1], "events": evs}
            if sh in deliv.index and fd >= deliv[sh] and sh in charges:
                rec["charges"] = charges[sh]
            files.setdefault(fd, []).append(rec)
    dates = sorted(files)
    prev = None
    n_resend = 0
    by_key = lambda ds: sorted(ds, key=lambda x: u01(np.array([x.toordinal()]), "f1")[0])[:3]
    resend_days = set(by_key([x for x in dates if pd.Timestamp(x) <= H0])) | set(by_key([x for x in dates if pd.Timestamp(x) > H0]))
    for fd in dates:
        (d / f"shipments_{fd:%Y%m%d}.json").write_text(json.dumps(files[fd], separators=(",", ":")))
        if fd in resend_days and prev is not None:
            (d / f"shipments_{fd:%Y%m%d}_resend.json").write_text(json.dumps(files[prev], separators=(",", ":")))
            log.add("F1", SYS, "file", f"shipments_{fd:%Y%m%d}_resend.json", "file", "", fd, {"duplicates_file": f"shipments_{prev:%Y%m%d}.json"}, "DEDUPE")
            n_resend += 1
        prev = fd
    return {"a_files": len(dates), "a_records": sum(len(v) for v in files.values()), "a_f7": len(dd), "a_resends": n_resend}


def _off(ts: pd.Series, tz: pd.Series) -> pd.Series:
    out = pd.Series("", index=ts.index, dtype=object)
    for z in tz.unique():
        m = (tz == z).values
        out.loc[m] = ts[m].dt.tz_convert(z).dt.strftime("%Y-%m-%d %H:%M:%S %z").values
    return out


def _carrier_b(T, s, ev, ch, log) -> dict:
    d = SRC / "freight" / "carrier_b"
    d.mkdir(parents=True, exist_ok=True)
    sb = s[s.carrier == "CARRIER_B"].copy()
    sb["tn"] = "1Z" + (900000000 + sb.shipment_id).astype(str)
    sb["ship_day"] = pd.to_datetime(sb.ship_ts_utc.dt.tz_convert("UTC").dt.tz_localize(None)).dt.normalize()
    deliv_day = ev[ev.status == "DELIVERED"].set_index("shipment_id").ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    sb = sb[(sb.ship_day <= E0) & ((sb.ship_day >= W0) | (sb.shipment_id.map(deliv_day) >= W0))].copy()
    sb["file_day"] = sb.ship_day.where(sb.ship_day >= W0, W0)  # pre-window shipments still in transit appear in the first file
    sb["ts_local"] = _off(sb.ship_ts_utc, sb.orig_tz)
    k = sb.shipment_id.values
    res = pick(k, "bres", 0.5)
    n_days = 0
    n_new = 0
    for day, g in sb.groupby("file_day", sort=True):
        if day < S2:
            out = pd.DataFrame({"tracking_no": g.tn.values, "reference": g.ref_w.values, "ship_ts_local": g.ts_local.values,
                                "service": np.where(pick(g.shipment_id.values, "bres", 0.5), "GND-RES", "GND-COM"), "weight_lb": g.w_weight.values,
                                "pieces": g.w_pieces.values, "origin_city": g.origin.values, "dest_city": g.dest.values})
        else:
            rs = pick(g.shipment_id.values, "bres", 0.5)
            dim = np.where(pick(g.shipment_id.values, "bdim", 0.25), (g.weight_lb.values * ufloat(g.shipment_id.values, "bdimf", 1.05, 1.6)).round(1), np.nan)
            out = pd.DataFrame({"tracking_no": g.tn.values, "reference": g.ref_w.values, "ship_ts_local": g.ts_local.values,
                                "service_level": "GROUND", "delivery_type": np.where(rs, "RES", "COM"), "wt_lbs": g.w_weight.values,
                                "dim_weight": dim, "pieces": g.w_pieces.values, "origin_city": g.origin.values, "dest_city": g.dest.values})
            n_new += 1
        out.to_csv(d / f"shipments_{day:%Y%m%d}.csv", index=False)
        n_days += 1
    log.add("S2", SYS, "carrier_b_shipments", "shipments_20260604.csv", "schema", "", S2,
            {"renamed": {"weight_lb": "wt_lbs"}, "split": {"service": ["service_level", "delivery_type"]}, "added": ["dim_weight"], "files_affected": n_new},
            "DETECT in same run; map or pause with alert")
    # tracking events
    evb = ev[ev.shipment_id.isin(sb.shipment_id)].merge(sb[["shipment_id", "tn", "dest_tz", "orig_tz"]], on="shipment_id")
    evb = evb[(evb.ts.dt.tz_convert("UTC").dt.tz_localize(None) >= W0) & (evb.ts.dt.tz_convert("UTC").dt.tz_localize(None) < E0 + pd.Timedelta(days=1))]
    evb["tz"] = np.where(evb.status.isin(["LABEL_CREATED", "PICKED_UP"]), evb.orig_tz, evb.dest_tz)
    evb["ts_local"] = _off(evb.ts, evb.tz)
    evb["fdate"] = evb.ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    for day, g in evb.groupby("fdate", sort=True):
        pd.DataFrame({"tracking_no": g.tn.values, "event_ts_local": g.ts_local.values, "status": g.status.values, "location": g["loc"].values}).to_csv(
            d / f"tracking_{day:%Y%m%d}.csv", index=False)
    # invoice charges on the delivery date
    ch = ch.merge(sb[["shipment_id", "tn"]], on="shipment_id")
    delv = evb[evb.status == "DELIVERED"].set_index("shipment_id").fdate
    ch["inv_day"] = ch.shipment_id.map(delv)
    ch = ch[ch.inv_day.notna()]
    ch["code"] = ch.charge_type.map(CODE_B)
    for day, g in ch.groupby("inv_day", sort=True):
        pd.DataFrame({"tracking_no": g.tn.values, "charge_code": g.code.values, "amount": g.amount.values,
                      "invoice_no": [f"INV{day:%y%m%d}" for _ in range(len(g))]}).to_csv(d / f"charges_{day:%Y%m%d}.csv", index=False)
    return {"b_shipment_files": n_days, "b_files_new_schema": n_new}
