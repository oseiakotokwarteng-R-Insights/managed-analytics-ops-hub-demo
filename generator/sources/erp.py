"""ERP source: nightly incremental CSV extracts (sales orders, purchase orders) + master data snapshots.
Timestamps are naive local time per warehouse. Defects E1-E6 and C1 are injected and logged."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as C
from .common import (SRC, W0, E0, H0, DefectLog, Truth, link_dates, order_no, pick, po_no, to_local, u01, uint, ufloat, vendor_city, write_by_date)

SYS = "ERP"
SHIP_VIA = {"OWN_FLEET": "OWN", "WILL_CALL": "WILLCALL", "CARRIER_A": "CARRA", "CARRIER_B": "CARRB"}
REQ_DAYS = {"WILL_CALL": 0, "OWN_FLEET": 1, "CARRIER_A": 3, "CARRIER_B": 2}
OLD_STAMP = pd.Timestamp("2020-01-15")


def acct(customer_id):
    return "C" + (pd.Series(customer_id).astype("int64") + 10000).astype(str)


def vendor_no(vendor_id):
    return "V" + (pd.Series(vendor_id).astype("int64") + 1000).astype(str)


def item_master(T: Truth, log: DefectLog):
    s = T.sku.copy()
    code = s.set_index("sku_id").sku_code
    first_recv = T.pol.groupby("sku_id").received_date.min()
    first_po = T.pol.merge(T.po[["po_id", "po_date"]], on="po_id").groupby("sku_id").po_date.min()
    new = s.lifecycle_kind.isin(["new_launch", "successor"])
    created = pd.Series(OLD_STAMP, index=s.sku_id.values)
    cr = (first_po.reindex(s.sku_id) - pd.Timedelta(days=3)).values
    created = pd.Series(np.where(new.values & ~pd.isna(cr), cr, created.values), index=s.sku_id.values)
    link = link_dates(T)
    bad_conv = (s.case_pack_qty.values > 1) & pick(s.sku_id.values, "e5b_sku", 0.04)
    succ_code = s.successor_sku_id.map(code)
    im = pd.DataFrame({
        "item_no": s.sku_code.values, "description": s.description.values,
        "category": s.category_id.map(dict(zip(T.cat.category_id, T.cat.name))).values, "uom": "EA",
        "case_qty": pd.Series(s.case_pack_qty.values).where((s.case_pack_qty.values > 1) & ~bad_conv).astype("Int64").values,
        "case_uom": np.where(s.case_pack_qty.values > 1, "CS", ""), "list_price": s.list_price.values, "std_cost": s.unit_cost.values,
        "weight_lb": s.weight_lb.values, "vendor_no": vendor_no(s.vendor_id).values,
        "status": np.where(s.discontinue_date.notna() & (s.discontinue_date <= E0), "D", "A"),
        "superseded_by": succ_code.fillna("").values, "created_date": created.dt.strftime("%Y-%m-%d").values,
        "wms_item_id": s.wms_item_id.values, "wms_link_date": link.dt.strftime("%Y-%m-%d").values})
    d = SRC / "erp"
    d.mkdir(parents=True, exist_ok=True)
    im.to_csv(d / "item_master.csv", index=False)
    log.add("E5b", SYS, "item_master", s.sku_code[bad_conv], "sku", s.sku_id[bad_conv], None,
            "case_qty missing for a case-packed item: CS lines for this item cannot be converted", "QUARANTINE")
    return bad_conv_set(s, bad_conv)


def bad_conv_set(s, mask):
    return set(s.sku_id[mask].tolist())


def other_masters(T: Truth, log: DefectLog):
    d = SRC / "erp"
    c = T.cust
    blank = pick(c.customer_id.values, "cust_dw", 0.20)
    wc = T.wh_code
    cm = pd.DataFrame({
        "cust_acct": acct(c.customer_id).values, "name": c.name.values, "cust_type": c.customer_type.values,
        "ship_to_city": c.ship_to_city.values, "default_wh": np.where(blank, "", c.default_warehouse_id.map(wc).values),
        "terms": c.payment_terms.values, "discount_pct": c.discount_pct.values,
        "created_date": c.active_from.dt.strftime("%Y-%m-%d").fillna("2020-01-15").values,
        "inactive_date": c.active_to.dt.strftime("%Y-%m-%d").fillna("").values})
    cm.to_csv(d / "customer_master.csv", index=False)
    v = T.vend
    vm = pd.DataFrame({"vendor_no": vendor_no(v.vendor_id).values, "name": v.name.values,
                       "city": vendor_city(T).reindex(v.vendor_id).values, "quoted_lead_time_days": v.quoted_lead_time_days.values,
                       "is_import": np.where(v.is_import, "Y", "N")})
    vm.to_csv(d / "vendor_master.csv", index=False)
    wm = pd.DataFrame({"wh_code": T.wh.warehouse_code, "name": T.wh.name, "city": T.wh.city, "timezone": T.wh.timezone})
    wm.to_csv(d / "warehouse_master.csv", index=False)
    return set(c.customer_id[blank].tolist())


def sales(T: Truth, log: DefectLog, bad_conv: set, blank_default: set):
    d = SRC / "erp"
    sku = T.sku.set_index("sku_id")
    L = T.lines.merge(T.orders[["order_id", "customer_id", "warehouse_id", "order_ts_utc", "delivery_mode", "n_lines"]], on="order_id")
    L["ono"] = order_no(L.order_id).values
    wcode = T.wh_code
    L["wh"] = L.warehouse_id.map(wcode)
    L["cp"] = L.sku_id.map(sku.case_pack_qty)
    win = (L.order_date >= W0).values
    n_win = int(win.sum())
    hist = win & (L.order_date <= H0).values
    n_hist = int(hist.sum())
    key = L.line_id.values

    # ---- line-level attributes and defects (applied to every version of the line)
    L["item_no"] = L.sku_id.map(sku.sku_code)
    L["uom"], L["qty_ord_erp"], L["price_erp"] = "EA", L.qty_ordered.astype(float), L.unit_price
    L["ship_wh"] = L.wh
    L["state_note"] = ""

    # E1: successor SKU still keyed under the superseded number
    old_of = {int(r.successor_sku_id): int(sid) for sid, r in sku.iterrows() if not pd.isna(r.successor_sku_id)}
    succ_intro = L.sku_id.map(sku.intro_date)
    cand = win & L.sku_id.isin(old_of.keys()).values & ((L.order_date - succ_intro).dt.days.between(0, 90)).values
    p1 = min(1.0, 0.008 * n_hist / max((cand & hist).sum(), 1))
    e1 = cand & pick(key, "e1", p1)
    L.loc[e1, "item_no"] = L.loc[e1, "sku_id"].map(old_of).map(sku.sku_code)
    log.add("E1", SYS, "sales_order_line", L.ono[e1] + "|" + L.line_no[e1].astype(str), "order_line", L.line_id[e1], L.order_date[e1],
            "successor SKU keyed as superseded predecessor", "AUTO-FIX")

    # E5 / E5b: non-base unit of measure (lines entered as cases)
    elig = win & (L.cp.values > 1) & (L.qty_ordered.values % L.cp.values == 0) & (L.line_status == "filled_same_day").values
    badsku = L.sku_id.isin(bad_conv).values
    p5b = min(1.0, 0.001 * n_hist / max((elig & badsku & hist).sum(), 1))
    e5b = elig & badsku & pick(key, "e5b", p5b)
    p5 = min(1.0, 0.015 * n_hist / max((elig & ~badsku & hist).sum(), 1))
    e5 = elig & ~badsku & pick(key, "e5", p5)
    for m, code, note in ((e5, "E5", "legitimate CS line, convertible via item master"), (e5b, "E5b", "CS line, item master has no case_qty")):
        L.loc[m, "uom"] = "CS"
        L.loc[m, "qty_ord_erp"] = L.loc[m, "qty_ordered"] / L.loc[m, "cp"]
        L.loc[m, "price_erp"] = (L.loc[m, "unit_price"] * L.loc[m, "cp"]).round(2)
    log.add("E5", SYS, "sales_order_line", L.ono[e5] + "|" + L.line_no[e5].astype(str), "order_line", L.line_id[e5], L.order_date[e5],
            "line in cases (legitimate)", "AUTO-FIX")
    log.add("E5b", SYS, "sales_order_line", L.ono[e5b] + "|" + L.line_no[e5b].astype(str), "order_line", L.line_id[e5b], L.order_date[e5b],
            "line in cases but item has no conversion factor", "QUARANTINE")

    # E3: zero / negative quantity
    e3 = win & ~e5 & ~e5b & pick(key, "e3", 0.0015)
    neg = u01(key, "e3neg") < 0.5
    L.loc[e3 & neg, "qty_ord_erp"] = -L.loc[e3 & neg, "qty_ordered"].astype(float)
    L.loc[e3 & ~neg, "qty_ord_erp"] = 0.0
    log.add("E3", SYS, "sales_order_line", L.ono[e3] + "|" + L.line_no[e3].astype(str), "order_line", L.line_id[e3], L.order_date[e3],
            "zero or negative quantity on a non-return line", "QUARANTINE")

    # E4: ship-from warehouse null or invalid
    e4 = win & pick(key, "e4", 0.003)
    bad = np.array(["", "WH-07", "PHX", "WH-0"])[uint(key, "e4v", 0, 3)]
    L.loc[e4, "ship_wh"] = bad[e4]
    cust_known = ~L.customer_id.isin(blank_default).values
    sibling = (L.n_lines.values > 1)
    rec = np.where(cust_known, "customer_default", np.where(sibling, "sibling_line", "none"))
    log.add("E4", SYS, "sales_order_line", L.ono[e4] + "|" + L.line_no[e4].astype(str), "order_line", L.line_id[e4], L.order_date[e4],
            [{"true_wh": w, "recoverable_via": r} for w, r in zip(L.wh[e4], rec[e4])], "AUTO-FIX or QUARANTINE")

    # ---- version rows: creation row + one row per later shipment date
    shp = T.mv[T.mv.movement_type == "ship"][["ref_id", "movement_date", "ts_utc", "qty_delta"]].rename(columns={"ref_id": "line_id", "movement_date": "date"})
    shp = shp.assign(q=-shp.qty_delta).groupby(["line_id", "date"], as_index=False).agg(q=("q", "sum"), ts=("ts_utc", "max"))
    in_win = shp.groupby("line_id").q.sum()
    pre_q = (L.set_index("line_id").qty_shipped - in_win.reindex(L.line_id).fillna(0).values).clip(lower=0)
    cre = pd.DataFrame({"line_id": L.line_id.values, "date": np.maximum(L.order_date.values, W0.to_datetime64())})
    cre["q"], cre["created"] = 0, 1
    cre["ts"] = pd.Series(pd.NaT, index=cre.index, dtype=shp.ts.dtype)
    ev = pd.concat([cre, shp.assign(created=0)], ignore_index=True)
    ev = ev.groupby(["line_id", "date"], as_index=False).agg(q=("q", "sum"), ts=("ts", "max"), created=("created", "max")).sort_values(["line_id", "date"])
    ev["cum"] = ev.groupby("line_id").q.cumsum() + ev.line_id.map(pre_q).values
    ev["last_ship"] = ev.date.where(ev.q > 0)
    ev["last_ship"] = ev.groupby("line_id").last_ship.ffill()
    ev = ev.merge(L, on="line_id", how="left")
    ts = ev.ts.where(ev.ts.notna(), ev.order_ts_utc)
    ts = ts.where(ev.created.eq(0), pd.concat([ts, ev.order_ts_utc], axis=1).max(axis=1))
    ev["last_modified"] = to_local(ts, ev.warehouse_id, T)
    ev["status"] = np.where(ev.cum >= ev.qty_ordered, "SHIPPED", np.where(ev.cum > 0, "PARTIAL", "BACKORDER"))
    conv = np.where(ev.uom == "CS", ev.cp, 1)
    ev["qty_shipped_erp"] = (ev.cum / conv)
    rows = ev[["date", "ono", "line_no", "item_no", "qty_ord_erp", "qty_shipped_erp", "uom", "price_erp", "ship_wh", "status", "last_ship",
               "last_modified", "line_id", "created"]].copy()
    rows.columns = ["extract_date", "order_no", "line_no", "item_no", "qty_ordered", "qty_shipped", "uom", "unit_price", "ship_wh", "status",
                    "last_ship_date", "last_modified", "_line_id", "_created"]

    # E6: quantity changed after shipment posted
    last = ev[(ev.status == "SHIPPED")].groupby("line_id").tail(1)
    last = last[(last.order_date >= W0).values & ~last.line_id.map(dict(zip(L.line_id, e3 | e5 | e5b))).values.astype(bool)]
    e6 = last[pick(last.line_id.values, "e6", 0.007)].copy()
    e6["d6"] = e6.date + pd.to_timedelta(uint(e6.line_id.values, "e6d", 1, 10), unit="D")
    e6 = e6[e6.d6 <= E0]
    newq = np.maximum(1, np.round(e6.qty_ordered * ufloat(e6.line_id.values, "e6q", 0.7, 1.3))).astype(int)
    newq = np.where(newq == e6.qty_ordered, e6.qty_ordered + 1, newq)
    r6 = pd.DataFrame({"extract_date": e6.d6.values, "order_no": e6.ono.values, "line_no": e6.line_no.values, "item_no": e6.item_no.values,
                       "qty_ordered": newq, "qty_shipped": e6.qty_shipped_erp.values,
                       "uom": "EA", "unit_price": e6.unit_price.values, "ship_wh": e6.ship_wh.values, "status": "SHIPPED",
                       "last_ship_date": e6.last_ship.values, "last_modified": (e6.d6 + pd.Timedelta(hours=10)).values,
                       "_line_id": e6.line_id.values, "_created": 0})
    log.add("E6", SYS, "sales_order_line", e6.ono + "|" + e6.line_no.astype(str), "order_line", e6.line_id, e6.d6,
            [{"original_qty": int(a), "new_qty": int(b)} for a, b in zip(e6.qty_ordered, newq)], "AUTO (versioned)")

    # E2: duplicate lines from re-keyed orders
    cr_rows = ev[(ev.created == 1) & (ev.order_date >= W0)]
    dup = cr_rows[pick(cr_rows.line_id.values, "e2", 0.006)].copy()
    kind = u01(dup.line_id.values, "e2k")
    dup["kind"] = np.where(kind < 0.70, "same_order", np.where(kind < 0.85, "new_order_exact", "new_order_near"))
    maxln = L.groupby("order_id").line_no.max()
    so = dup[dup.kind == "same_order"].copy()
    so["new_ln"] = so.order_id.map(maxln) + so.groupby("order_id").cumcount() + 1
    no_ = dup[dup.kind != "same_order"].copy()
    no_["new_ono"] = "SO-" + (100000 + 2 * no_.order_id + 1).astype(str)
    no_["kind"] = no_.groupby("new_ono").kind.transform("first")  # one re-keyed order per original, however many lines it carries
    no_["new_ln"] = no_.groupby("new_ono").cumcount() + 1
    g1 = no_.groupby("new_ono").line_id.transform("first").values
    no_["gap_min"] = np.where(no_.kind == "new_order_exact", uint(g1, "e2g", 2, 9), uint(g1, "e2g", 11, 25))
    common = ["extract_date", "item_no", "qty_ordered", "qty_shipped", "uom", "unit_price", "ship_wh", "status", "last_ship_date", "last_modified", "_line_id", "_created"]

    def mk(df, ono, ln, lm):
        return pd.DataFrame({"extract_date": df.date.values, "order_no": ono, "line_no": ln, "item_no": df.item_no.values,
                             "qty_ordered": df.qty_ord_erp.values, "qty_shipped": 0.0, "uom": df.uom.values, "unit_price": df.price_erp.values,
                             "ship_wh": df.ship_wh.values, "status": "OPEN", "last_ship_date": pd.NaT, "last_modified": lm,
                             "_line_id": df.line_id.values, "_created": 0})
    r2a = mk(so, so.ono.values, so.new_ln.values, to_local(so.order_ts_utc, so.warehouse_id, T).values)
    r2b = mk(no_, no_.new_ono.values, no_.new_ln.values, (to_local(no_.order_ts_utc, no_.warehouse_id, T) + pd.to_timedelta(no_.gap_min, unit="m")).values)
    log.add("E2", SYS, "sales_order_line", pd.Series(r2a.order_no.values + "|" + r2a.line_no.astype(str).values), "order_line", so.line_id, so.date,
            "duplicate line inside the same order", "DEDUPE")
    log.add("E2", SYS, "sales_order_line", pd.Series(r2b.order_no.values + "|" + r2b.line_no.astype(str).values), "order_line", no_.line_id, no_.date,
            [{"variant": k, "gap_min": int(g), "original_order": o} for k, g, o in zip(no_.kind, no_.gap_min, no_.ono)],
            "DEDUPE (exact) / FLAG (near)")

    allrows = pd.concat([rows, r6, r2a, r2b], ignore_index=True)
    allrows["_line_id"] = allrows["_line_id"].astype("int64")
    for col in ("qty_ordered", "qty_shipped"):
        allrows[col] = allrows[col].round(4)
    allrows["last_ship_date"] = pd.to_datetime(allrows.last_ship_date).dt.strftime("%Y-%m-%d")
    allrows["last_modified"] = pd.to_datetime(allrows.last_modified).dt.strftime("%Y-%m-%d %H:%M:%S")
    out = allrows.drop(columns=["_line_id", "_created"])
    for col in ("qty_ordered", "qty_shipped"):
        out[col] = out[col].map(lambda v: f"{v:g}")
    out["extract_date"] = pd.to_datetime(out.extract_date)
    n_files = write_by_date(out.assign(extract_date=out.extract_date), "extract_date", d / "sales_order_line", "so_line")

    # ---- headers
    done = ev.assign(done=(ev.cum >= ev.qty_ordered)).sort_values(["line_id", "date"])
    first_done = done[done.done].groupby("line_id").date.min()
    od = T.orders.copy()
    od["ono"] = order_no(od.order_id).values
    ld = L[["line_id", "order_id"]].assign(done=L.line_id.map(first_done))
    all_done = ld.groupby("order_id").done.agg(lambda s: s.notna().all())
    comp_date = ld.groupby("order_id").done.max()
    od["comp"] = od.order_id.map(comp_date).where(od.order_id.map(all_done))
    od["create_date"] = np.maximum(od.order_date.values, W0.to_datetime64())
    od["ts_local"] = to_local(od.order_ts_utc, od.warehouse_id, T)
    od["req"] = od.order_date + pd.to_timedelta(od.delivery_mode.map(REQ_DAYS), unit="D")
    done_at_create = od.comp.notna() & (od.comp <= od.create_date)

    def hdr(df, status, date, lm):
        return pd.DataFrame({"extract_date": date, "order_no": df.ono.values, "cust_acct": acct(df.customer_id).values,
                             "order_ts_local": df.ts_local.dt.strftime("%Y-%m-%d %H:%M:%S").values,
                             "req_date": df.req.dt.strftime("%Y-%m-%d").values, "ship_via": df.delivery_mode.map(SHIP_VIA).values,
                             "status": status, "last_modified": pd.Series(pd.to_datetime(np.asarray(lm))).dt.strftime("%Y-%m-%d %H:%M:%S").values})
    h1 = hdr(od, np.where(done_at_create, "COMPLETE", "OPEN"), od.create_date.values, od.ts_local.values)
    later = od[od.comp.notna() & (od.comp <= E0) & (od.comp > od.create_date)]
    h2 = hdr(later, "COMPLETE", later.comp.values, (later.comp + pd.Timedelta(hours=17)).values)
    nn = no_.drop_duplicates("new_ono")
    o3 = od.set_index("order_id").loc[nn.order_id.values].reset_index()
    gap = pd.to_timedelta(nn.gap_min.values, unit="m")
    d3 = o3.assign(ono=nn.new_ono.values, ts_local=o3.ts_local.values + gap)
    h3 = hdr(d3, "OPEN", nn.date.values, d3.ts_local.values)
    hdrs = pd.concat([h1, h2, h3], ignore_index=True)
    hdrs["extract_date"] = pd.to_datetime(hdrs.extract_date)
    write_by_date(hdrs, "extract_date", d / "sales_order_header", "so_header")
    return {"lines_window": n_win, "e1_candidates": int(cand.sum()), "e1_rate": float(e1.sum() / n_win), "e5_rate": float(e5.sum() / n_win),
            "e5b_rate": float(e5b.sum() / n_win), "line_rows": len(out), "header_rows": len(hdrs), "line_files": n_files}


def purchasing(T: Truth, log: DefectLog):
    d = SRC / "erp"
    po = T.po.copy()
    po["pno"] = po_no(po.po_id).values
    pl = T.pol.merge(po[["po_id", "pno", "vendor_id", "warehouse_id", "po_date", "promised_date"]], on="po_id")
    pl = pl.sort_values(["po_id", "po_line_id"])
    pl["line_no"] = pl.groupby("po_id").cumcount() + 1
    pl["item_no"] = pl.sku_id.map(T.sku.set_index("sku_id").sku_code)
    pl["create_date"] = np.maximum(pl.po_date.values, W0.to_datetime64())
    short = (pl.qty_received < pl.qty_ordered).values
    rcvd = (pl.received_date <= E0).values
    typo = rcvd & pick(pl.po_line_id.values, "c1t", 0.0065)
    full = rcvd & short & pick(pl.po_line_id.values, "c1s", 0.05) & ~typo
    kind = u01(pl.po_line_id.values, "c1k")
    q = pl.qty_received.values.astype(np.int64)
    qt = np.where(kind < 0.34, q * 10, np.where(kind < 0.67, np.maximum(q // 10, 1), np.where(q > 9, (q // 10) * 10 + (q % 10 * 7 % 10) + 1, q + 5)))
    qt = np.where(qt == q, q + 7, qt)
    pl["qty_recv_erp"] = np.where(typo, qt, np.where(full, pl.qty_ordered, pl.qty_received))
    pk = pl.pno + "|" + pl.line_no.astype(str)
    log.add("C1", SYS, "po_line", pk[typo], "po_line", pl.po_line_id[typo], pl.received_date[typo],
            [{"wms_qty": int(a), "erp_qty": int(b), "mode": "keying_error"} for a, b in zip(q[typo], qt[typo])], "FLAG")
    log.add("C1", SYS, "po_line", pk[full], "po_line", pl.po_line_id[full], pl.received_date[full],
            [{"wms_qty": int(a), "erp_qty": int(b), "mode": "short_shipment_recorded_full"} for a, b in zip(q[full], pl.qty_ordered.values[full])], "FLAG")
    vno = vendor_no(pl.vendor_id).values
    first_day_recv = (pl.received_date <= pl.create_date).values  # created and received on the same extract day
    lines_cre = pd.DataFrame({"extract_date": pl.create_date.values, "po_no": pl.pno.values, "line_no": pl.line_no.values, "item_no": pl.item_no.values,
                              "qty_ordered": pl.qty_ordered.values, "uom": "EA", "unit_cost": pl.unit_cost.values, "qty_received": 0,
                              "received_date": "", "status": "OPEN"})[~first_day_recv]
    r = pl[rcvd]
    lines_rec = pd.DataFrame({"extract_date": r.received_date.values, "po_no": r.pno.values, "line_no": r.line_no.values, "item_no": r.item_no.values,
                              "qty_ordered": r.qty_ordered.values, "uom": "EA", "unit_cost": r.unit_cost.values, "qty_received": r.qty_recv_erp.values,
                              "received_date": r.received_date.dt.strftime("%Y-%m-%d").values,
                              "status": np.where(r.qty_recv_erp.values >= r.qty_ordered.values, "RECEIVED", "PARTIAL")})
    lines = pd.concat([lines_cre, lines_rec], ignore_index=True)
    lines["extract_date"] = pd.to_datetime(lines.extract_date)
    write_by_date(lines, "extract_date", d / "po_line", "po_line")
    h = po.merge(pl.groupby("po_id").agg(complete=("qty_recv_erp", "size")).reset_index(), on="po_id", how="left")
    hc = pd.DataFrame({"extract_date": np.maximum(h.po_date.values, W0.to_datetime64()), "po_no": h.pno.values, "vendor_no": vendor_no(h.vendor_id).values,
                       "ship_to_wh": h.warehouse_id.map(T.wh_code).values, "po_date": h.po_date.dt.strftime("%Y-%m-%d").values,
                       "promised_date": h.promised_date.dt.strftime("%Y-%m-%d").values, "status": "OPEN", "received_date": ""})
    hr = h[h.received_date <= E0]
    hrc = pd.DataFrame({"extract_date": hr.received_date.values, "po_no": hr.pno.values, "vendor_no": vendor_no(hr.vendor_id).values,
                        "ship_to_wh": hr.warehouse_id.map(T.wh_code).values, "po_date": hr.po_date.dt.strftime("%Y-%m-%d").values,
                        "promised_date": hr.promised_date.dt.strftime("%Y-%m-%d").values, "status": "RECEIVED",
                        "received_date": hr.received_date.dt.strftime("%Y-%m-%d").values})
    hc = hc[~(h.received_date <= np.maximum(h.po_date, W0)).values]
    hh = pd.concat([hc, hrc], ignore_index=True)
    write_by_date(hh, "extract_date", d / "po_header", "po_header")
    return {"po_lines": len(pl), "c1_typo": int(typo.sum()), "c1_short_full": int(full.sum()), "pos": len(po), "c1_po_rate": float(pd.Series(pl.pno[typo | full]).nunique() / len(po))}


def build(T: Truth, log: DefectLog) -> dict:
    bad = item_master(T, log)
    blank = other_masters(T, log)
    stats = {}
    stats.update(sales(T, log, bad, blank))
    stats.update(purchasing(T, log))
    return stats
