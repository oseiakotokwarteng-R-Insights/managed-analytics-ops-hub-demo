"""Legacy source: the acquired Albuquerque (WH-05) system. Weekly CSV dumps of inventory transactions, text-typed columns,
date-only values in two terminal-dependent formats, plus vendor and item-cost tables. Defects L1, L2, L4, L5, L6 (and S1's
unposted adjustments, handled through the count adjustments) are injected and logged."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config as C
from .common import (SRC, W0, E0, DefectLog, Truth, order_no, pick, po_no, u01, uint, ufloat)
from .wms import c3_plan

SYS = "LEGACY"
WH = 5
EFFECT = {"RCPT": 1, "ISSU": -1, "XFER": 1, "OPEN": 1}
STREETS = ["Industrial Blvd", "Commerce Dr", "Mill Rd", "Railroad Ave", "Warehouse Way", "Main St", "Frontage Rd", "Enterprise Pkwy"]


def lv(vendor_id):
    return "LV" + (pd.Series(vendor_id).astype("int64") + 2000).astype(str)


def prepare(T: Truth, log: DefectLog) -> pd.DataFrame:
    mv = T.mv[(T.mv.warehouse_id == WH) & T.mv.movement_type.isin(["receipt", "ship", "transfer_in", "disposal"])].copy()
    ono = pd.Series(order_no(T.lines.order_id).values, index=T.lines.line_id.values)
    pol = T.pol.merge(T.po[["po_id", "vendor_id"]], on="po_id")
    pno = pd.Series(po_no(pol.po_id).values, index=pol.po_line_id.values)
    pven = pd.Series(pol.vendor_id.values, index=pol.po_line_id.values)
    pcost = pd.Series(pol.unit_cost.values, index=pol.po_line_id.values)
    t = mv.movement_type
    ref = np.where(t == "ship", mv.ref_id.map(ono), np.where(t == "receipt", mv.ref_id.map(pno), np.where(t == "transfer_in", "TO-" + mv.ref_id.astype(str).str.zfill(6), "")))
    df = pd.DataFrame({
        "tkey": mv.movement_id.values, "etype": t.map({"receipt": "RCPT", "ship": "ISSU", "transfer_in": "XFER", "disposal": "ADJ"}).values,
        "sku_id": mv.sku_id.values, "wh_id": WH, "qty": mv.qty_delta.abs().values, "ref_no": ref, "mdate": mv.movement_date.values,
        "vendor_id": np.where(t == "receipt", mv.ref_id.map(pven), 0), "unit_cost": np.where(t == "receipt", mv.ref_id.map(pcost), np.nan),
        "sign": np.where(t == "ship", -1, np.where(t == "disposal", -1, 1)), "memo": np.where(t == "disposal", "OBSOL", "")})
    op = T.opening[(T.opening.warehouse_id == WH) & (T.opening.onhand_qty > 0)]
    ob = pd.DataFrame({"tkey": -1 - np.arange(len(op)), "etype": "OPEN", "sku_id": op.sku_id.values, "wh_id": WH, "qty": op.onhand_qty.values,
                       "ref_no": "", "mdate": W0 - pd.Timedelta(days=1), "vendor_id": 0, "unit_cost": np.nan, "sign": 1, "memo": "OPENING"})
    df = pd.concat([df, ob], ignore_index=True)
    plan = c3_plan(T)  # transfers whose receiving side never reached the legacy system
    miss = "TO-" + plan.transfer_id[(plan.drop_side == "in") & (plan.to_warehouse_id == WH)].astype(str).str.zfill(6)
    df = df[~((df.etype == "XFER") & df.ref_no.isin(miss))]
    df["src"] = "movement"
    return df.reset_index(drop=True)


def book_effects(df: pd.DataFrame) -> pd.DataFrame:
    s = df.etype.map(EFFECT).fillna(0).astype(int)
    adj = df.etype == "ADJ"
    s[adj] = df.sign[adj]
    return pd.DataFrame({"sku_id": df.sku_id.values, "wh_id": df.wh_id.values, "mdate": df.mdate.values, "eff": (s * df.qty).values})


def vendor_tables(T: Truth, log: DefectLog):
    v = T.vend
    d = SRC / "legacy"
    d.mkdir(parents=True, exist_ok=True)
    k = v.vendor_id.values
    street = np.array(STREETS)[uint(k, "street", 0, len(STREETS) - 1)]
    from .common import vendor_city
    city = vendor_city(T).reindex(k).values
    base = pd.DataFrame({"vendor_id": lv(v.vendor_id).values, "vendor_name": v.name.str.upper().values,
                         "address": [f"{uint(np.array([i]), 'bn', 100, 9899)[0]} {s}" for i, s in zip(k, street)], "city_state": city,
                         "phone": [f"({uint(np.array([i]), 'ph', 200, 989)[0]}) {uint(np.array([i]), 'ph2', 200, 989)[0]}-{uint(np.array([i]), 'ph3', 1000, 9999)[0]}" for i in k],
                         "terms": np.where(v.is_import, "NET60", "NET30"), "status": "A"})
    order = np.argsort(u01(k, "l6"))[:7]
    dups, kinds = [], []
    for j, idx in enumerate(order):
        r = base.iloc[idx].copy()
        r["vendor_id"] = f"LV{2200 + j:04d}"
        if j < 5:  # strong match: same address and phone, cosmetic name change
            r["vendor_name"] = r.vendor_name.replace("MANUFACTURING", "MFG").replace("SUPPLY", "SUPPLY INC.").replace("INDUSTRIES", "IND.")
            if r.vendor_name == base.iloc[idx].vendor_name:
                r["vendor_name"] += " INC"
            kinds.append("strong")
        else:  # weak match: abbreviated name, different address and phone formatting
            r["vendor_name"] = " ".join(w[:4] for w in base.iloc[idx].vendor_name.split())
            r["address"] = r.address.replace(" St", " Street").replace(" Rd", " Road") + " Ste 2"
            r["phone"] = r.phone.replace("(", "").replace(") ", "-")
            kinds.append("weak")
        dups.append(r)
    dup_df = pd.DataFrame(dups)
    vend = pd.concat([base, dup_df], ignore_index=True)
    vend.to_csv(d / "vendor.csv", index=False)
    log.add("L6", SYS, "vendor", dup_df.vendor_id.values, "vendor", v.vendor_id.values[order],
            None, [{"duplicate_of": base.vendor_id.iloc[i], "match": kd} for i, kd in zip(order, kinds)], "AUTO-merge (strong) / REVIEW (weak)")
    # historical costs, one row per price step
    s = T.sku
    steps = [pd.Timestamp("2024-01-01")] + [pd.Timestamp(x) for x in C.PRICE_STEPS]
    rows = []
    for st in steps:
        idx = T.cal.date.searchsorted(st)
        pidx = float(T.cal.price_index.iloc[min(idx, len(T.cal) - 1)]) if st >= T.cal.date.iloc[0] else 1.0
        rows.append(pd.DataFrame({"item_code": s.legacy_code.values, "vendor_id": lv(s.vendor_id).values,
                                  "std_cost": ["$" + f"{c * pidx:.4f}" for c in s.unit_cost.values],
                                  "eff_date": st.strftime("%m/%d/%y")}))
    pd.concat(rows, ignore_index=True).to_csv(d / "item_cost.csv", index=False)
    return {int(vid): int(2200 + j) for j, vid in enumerate(v.vendor_id.values[order])}


def finish(T: Truth, df: pd.DataFrame, log: DefectLog) -> dict:
    dup_vendor = vendor_tables(T, log)
    df = df.sort_values(["mdate", "tkey"], kind="stable").reset_index(drop=True)
    df["tid"] = [f"L{i:07d}" for i in range(1, len(df) + 1)]
    key = df.tkey.values + 10 ** 9 * (df.etype == "ADJ").values
    sku = T.sku.set_index("sku_id")
    code = df.sku_id.map(sku.legacy_code)
    padded = pick(key, "pad", 0.40)
    item_code = np.where(padded, code + "  ", code)
    # terminal-dependent date text (L2)
    term = np.where(u01(key, "term") < 0.6, "T1", "T2")
    blank = pick(key, "termblank", 0.005)
    term = np.where(blank, "", term)
    md = pd.to_datetime(df.mdate)
    dayfirst_blank = u01(key, "dfb") < 0.5
    t1 = md.dt.strftime("%m/%d/%y")
    t2 = md.dt.strftime("%d-%b-%Y")
    tb = np.where(dayfirst_blank, md.dt.strftime("%d/%m/%y"), md.dt.strftime("%m/%d/%y"))
    date_txt = np.where(term == "T1", t1, np.where(term == "T2", t2, tb))
    amb = blank & (md.dt.day.values <= 12) & (md.dt.day.values != md.dt.month.values)
    log.add("L2", SYS, "inv_trans", df.tid[amb], "inventory_txn", df.tkey[amb], df.mdate[amb],
            [{"true_date": str(d.date()), "format_guess_risk": "MM/DD vs DD/MM"} for d in md[amb]], "FLAG")
    # numeric text (L5)
    q = df.qty.astype(int).values
    comma = (q >= 1000) & (u01(key, "comma") < 0.5)
    qty_txt = np.where(comma, [f"{v:,}" for v in q], q.astype(str))
    spaced = pick(key, "qsp", 0.10)
    qty_txt = np.where(spaced, " " + qty_txt, qty_txt)
    garb = pick(key, "l5", 0.003)
    gl = np.array(["N/A", "1O0", "12..5", "--", "", "#VALUE"])[uint(key, "l5v", 0, 5)]
    qty_txt = np.where(garb, gl, qty_txt)
    log.add("L5", SYS, "inv_trans", df.tid[garb], "inventory_txn", df.tkey[garb], df.mdate[garb],
            [{"true_qty": int(v), "written": w} for v, w in zip(q[garb], gl[garb])], "QUARANTINE")
    cost_txt = np.where(df.unit_cost.notna(), ["$" + f"{c:.4f}" if c == c else "" for c in df.unit_cost.values], "")
    # vendor ids: duplicates (L6) and orphans (L4) on receipts
    party = np.where(df.vendor_id > 0, lv(df.vendor_id.where(df.vendor_id > 0, 1)).values, "")
    usedup = np.array([int(v) in dup_vendor for v in df.vendor_id.values]) & (u01(key, "l6u") < 0.5)
    party = np.where(usedup, ["LV" + f"{dup_vendor.get(int(v), 0):04d}" for v in df.vendor_id.values], party)
    orphan = (df.etype == "RCPT").values & pick(key, "l4", 0.05)
    party = np.where(orphan, ["LV" + str(9000 + n) for n in uint(key, "l4v", 0, 999)], party)
    log.add("L4", SYS, "inv_trans", df.tid[orphan], "inventory_txn", df.tkey[orphan], df.mdate[orphan],
            [{"true_vendor_id": int(v)} for v in df.vendor_id[orphan]], "QUARANTINE")
    # ambiguity of the 8-char code (L1)
    g = sku[["legacy_code", "intro_date", "discontinue_date", "lifecycle_kind"]].reset_index()
    shared = g[g.duplicated("legacy_code", keep=False)]
    rows = df[df.sku_id.isin(shared.sku_id)][["tid", "tkey", "sku_id", "mdate"]].copy()
    rows["legacy_code"] = rows.sku_id.map(sku.legacy_code)
    other = rows.merge(shared, on="legacy_code", suffixes=("", "_o")).query("sku_id != sku_id_o")
    d0 = pd.to_datetime(other.mdate)
    active = (other.intro_date.isna() | (d0 >= other.intro_date)) & (other.discontinue_date.isna() | (d0 <= other.discontinue_date + pd.Timedelta(days=30)))
    ambiguous = other[active].groupby("tid").sku_id_o.apply(list)
    rows["ambiguous"] = rows.tid.isin(ambiguous.index)
    log.add("L1", SYS, "inv_trans", rows.tid, "inventory_txn", rows.tkey, rows.mdate,
            [{"true_sku_id": int(s), "ambiguous": bool(a), "other_candidates": ambiguous.get(t, [])} for s, a, t in zip(rows.sku_id, rows.ambiguous, rows.tid)],
            "AUTO where unique by date, REVIEW where ambiguous")
    ttype = np.where(df.etype == "ADJ", np.where(df["sign"] > 0, "ADJ+", "ADJ-"), df.etype)
    out = pd.DataFrame({"trans_id": df.tid.values, "item_code": item_code, "trans_type": ttype, "trans_date": date_txt, "qty": qty_txt,
                        "unit_cost": cost_txt, "ref_no": df.ref_no.values, "party_id": party, "entry_terminal": term, "memo": df.memo.values})
    wk = pd.to_datetime(df.mdate)
    out["_dump"] = (wk + pd.to_timedelta(6 - wk.dt.weekday, unit="D")).dt.strftime("%Y%m%d")
    out = out[pd.to_datetime(out._dump) <= E0 + pd.Timedelta(days=6)]
    folder = SRC / "legacy"
    n = 0
    for dump, g in out.groupby("_dump", sort=True):
        g.drop(columns="_dump").to_csv(folder / f"inv_trans_{dump}.csv", index=False)
        n += 1
    return {"legacy_rows": len(out), "legacy_files": n, "l1_rows_shared_code": len(rows), "l1_ambiguous": int(rows.ambiguous.sum()),
            "l2_ambiguous": int(amb.sum()), "l4": int(orphan.sum()), "l5": int(garb.sum())}
