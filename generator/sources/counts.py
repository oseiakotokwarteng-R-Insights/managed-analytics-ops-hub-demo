"""Cycle counts and the spreadsheet source. Counts are the independent physical check: counted quantity is the TRUE on-hand at the
start of the count day, compared with each system's book at that moment. ~60% of variances are posted back as adjustments.
Defects X1-X6 and the deliberately undetectable U1-U3 live here."""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .. import config as C
from .common import (SRC, W0, E0, H0, DefectLog, Truth, pick, po_no, u01, uint, ufloat, vendor_city)
from .wms import DRIFT_DATE, bins_table

SYS = "SHEETS"
N_COUNTS = {"A": 4, "B": 2, "C": 1}
COUNTERS = {1: ["D. Reyes", "K. Nguyen", "T. Boyd"], 2: ["T. Okafor", "L. Ramos", "S. Whitfield"], 3: ["J. Marsh", "P. Delacroix", "A. Kim"],
            4: ["R. Castillo", "M. Hale", "E. Torres"], 5: ["B. Lindqvist", "C. Nakamura", "H. Ortega"], 6: ["F. Salazar", "G. Pratt", "N. Ibarra"]}
HEADERS = [["SKU", "Description", "Bin", "UOM", "Counted Qty", "Counted By", "Count Date", "Notes"],
           ["Item #", "Item Description", "Location", "Unit", "Qty Counted", "Counter", "Date", "Comments"],
           ["Part No", "Desc", "Bin", "UOM", "On Hand", "Initials", "Counted On", "Notes"],
           ["SKU", "Description", "Bin", "UOM", "OH", "Counted By", "Count Date", "Notes"]]
NOTES = ["recount requested", "damaged units not included", "aisle blocked, counted next day", "see Mike re: overflow", "partial pallet", "relabeled"]
U1_MONTHS = (pd.Timestamp("2026-02-01"), pd.Timestamp("2026-04-30"))


def _open_days(T: Truth):
    cal = T.cal[(T.cal.date >= W0 - pd.Timedelta(days=1))].reset_index(drop=True)
    return cal.date.values, cal.is_open_day.values


def schedule(T: Truth, log: DefectLog) -> pd.DataFrame:
    s = T.sku.set_index("sku_id")
    p = T.pairs.copy()
    p["cls"] = p.sku_id.map(s.abc_class)
    p["intro"] = p.sku_id.map(s.intro_date)
    p["disc"] = p.sku_id.map(s.discontinue_date)
    days = (H0 - W0).days + 1  # one counting cycle is the frozen two-year window; later cycles repeat the pattern with fresh dates
    cycles = -(-((E0 - W0).days + 1) // days)
    rows = []
    for m in range(cycles):
        for k in range(4):
            sub = p[p.cls.map(N_COUNTS) > k]
            seg = days // sub.cls.map(N_COUNTS)
            off = days * m + (seg * k + (u01(sub.pair_id.values * 16 + k + m * 10 ** 9, "cnt") * seg).astype(int))
            rows.append(pd.DataFrame({"pair_id": sub.pair_id.values, "sku_id": sub.sku_id.values, "wh_id": sub.warehouse_id.values, "k": k, "cycle": m,
                                      "count_date": W0 + pd.to_timedelta(off.values, unit="D"), "intro": sub.intro.values, "disc": sub.disc.values}))
    c = pd.concat(rows, ignore_index=True)
    dates, is_open = _open_days(T)
    open_dates = dates[is_open]
    idx = np.minimum(open_dates.searchsorted(c.count_date.values.astype("datetime64[ns]")), len(open_dates) - 1)
    c["count_date"] = pd.to_datetime(open_dates[idx])
    ok = (c.intro.isna() | (c.count_date >= c.intro + pd.Timedelta(days=10))) & (c.disc.isna() | (c.count_date <= c.disc + pd.Timedelta(days=20)))
    c = c[ok & (c.count_date <= E0)].drop(columns=["intro", "disc"])
    # S1: pairs affected by the phantom-stock loss are not counted until the discovery count
    s1 = T.ent[T.ent.scenario_id == "S1"][["sku_id", "warehouse_id"]].rename(columns={"warehouse_id": "wh_id"}).merge(T.pairs[["pair_id", "sku_id", "warehouse_id"]].rename(columns={"warehouse_id": "wh_id"}), on=["sku_id", "wh_id"])
    in_s1 = c.pair_id.isin(s1.pair_id) & (c.count_date >= pd.Timestamp(C.S1_START)) & (c.count_date < pd.Timestamp(C.S1_DISCOVERED))
    c = c[~in_s1]
    forced = pd.DataFrame({"pair_id": s1.pair_id.values, "sku_id": s1.sku_id.values, "wh_id": s1.wh_id.values, "k": 9, "count_date": pd.Timestamp(C.S1_DISCOVERED)})
    c = pd.concat([c, forced], ignore_index=True).drop_duplicates(["pair_id", "count_date"])
    c["cycle"] = c.cycle.fillna(0).astype(int)
    c["count_id"] = c.cycle * 10 ** 9 + c.pair_id * 16 + c.k
    c["forced_s1"] = c.k == 9
    return c.sort_values(["pair_id", "count_date"]).reset_index(drop=True)


def true_counts(T: Truth, c: pd.DataFrame) -> pd.DataFrame:
    """True on-hand at the end of the previous day for each count."""
    con = duckdb.connect()
    cc = c.assign(prev=c.count_date - pd.Timedelta(days=1))[["count_id", "sku_id", "wh_id", "prev"]].copy()
    cc["prev"] = cc.prev.dt.date
    con.register("cc", cc)
    p_oh = str(C.TRUTH_DIR / "truth_onhand_daily.parquet").replace("\\", "/")
    p_ob = str(C.TRUTH_DIR / "truth_opening_balance.parquet").replace("\\", "/")
    q = con.execute(f"""SELECT c.count_id, COALESCE(o.onhand_qty, b.onhand_qty, 0) q FROM cc c
        LEFT JOIN read_parquet('{p_oh}') o ON o.sku_id=c.sku_id AND o.warehouse_id=c.wh_id AND o.snapshot_date=c.prev
        LEFT JOIN read_parquet('{p_ob}') b ON b.sku_id=c.sku_id AND b.warehouse_id=c.wh_id AND b.as_of_date=c.prev""").fetchdf()
    return c.merge(q, on="count_id").rename(columns={"q": "true_qty"})


def book_before(c: pd.DataFrame, book: pd.DataFrame) -> pd.Series:
    """System book (events only) at the end of the day before each count."""
    book = book.assign(sku_id=book.sku_id.astype("int64"), wh_id=book.wh_id.astype("int64"), mdate=pd.to_datetime(book.mdate).astype("datetime64[ns]"))
    b = book.groupby(["sku_id", "wh_id", "mdate"], as_index=False).eff.sum().sort_values("mdate")
    b["cum"] = b.groupby(["sku_id", "wh_id"]).eff.cumsum()
    left = c.assign(prev=(c.count_date - pd.Timedelta(days=1)).astype("datetime64[ns]"), sku_id=c.sku_id.astype("int64"), wh_id=c.wh_id.astype("int64")).sort_values("prev")
    m = pd.merge_asof(left, b[["sku_id", "wh_id", "mdate", "cum"]], left_on="prev", right_on="mdate", by=["sku_id", "wh_id"], direction="backward")
    return m.set_index("count_id").cum.fillna(0)


def make_counts(T: Truth, wms_book: pd.DataFrame, leg_book: pd.DataFrame, log: DefectLog):
    c = true_counts(T, schedule(T, log))
    ev_book = pd.concat([wms_book, leg_book], ignore_index=True)
    c["event_cum"] = c.count_id.map(book_before(c, ev_book)).values
    c = c.sort_values(["pair_id", "count_date"]).reset_index(drop=True)
    c["rank"] = c.groupby("pair_id").cumcount()
    applied = {}
    book, var, post = [], [], []
    for r in sorted(c["rank"].unique()):
        m = c["rank"] == r
        sub = c[m]
        b = sub.event_cum.values + sub.pair_id.map(applied).fillna(0).values
        v = sub.true_qty.values - b
        posted = (v != 0) & (pick(sub.count_id.values, "adjpost", 0.6) | sub.forced_s1.values)
        for pid, vv, pp in zip(sub.pair_id.values, v, posted):
            if pp:
                applied[pid] = applied.get(pid, 0) + vv
        book.append(pd.Series(b, index=sub.index))
        var.append(pd.Series(v, index=sub.index))
        post.append(pd.Series(posted, index=sub.index))
    c["book_qty"] = pd.concat(book)
    c["variance"] = pd.concat(var)
    c["posted"] = pd.concat(post)
    lag = np.where(c.forced_s1, 1, uint(c.count_id.values, "adjlag", 1, 5))
    c["post_date"] = c.count_date + pd.to_timedelta(lag, unit="D")
    # adjustments become events in the owning system
    adj = c[c.posted & (c.post_date <= E0)]
    adj_ev = pd.DataFrame({"mv_id": 2 * 10 ** 12 + adj.count_id.values, "k": 0, "etype": "ADJUST", "wh_id": adj.wh_id.values, "sku_id": adj.sku_id.values,
                           "qty": adj.variance.abs().values, "ref_no": "CC-" + adj.count_id.astype(str).values, "mdate": adj.post_date.values,
                           "mtype": "count_adjust", "line_or_ref": adj.count_id.values, "eid_key": 2 * 10 ** 12 + adj.count_id.values,
                           "direction": np.where(adj.variance.values > 0, "IN", "OUT"), "ref_type": "CC", "reason": "CYCLE_COUNT",
                           "book_sku": adj.sku_id.values, "src": "count_adjust"})
    # post time: mid-afternoon local, expressed in UTC
    ts = []
    for w, d in zip(adj_ev.wh_id.values, adj_ev.mdate.values):
        ts.append(pd.Timestamp(d).tz_localize(T.wh_tz[int(w)]).tz_convert("UTC") + pd.Timedelta(hours=15))
    adj_ev["ts"] = pd.to_datetime(ts, utc=True) if ts else pd.NaT
    adj_ev["order_ts"] = pd.NaT
    wms_adj = adj_ev[adj_ev.wh_id != 5].copy()
    leg_adj = adj_ev[adj_ev.wh_id == 5].copy()
    leg_adj = leg_adj.assign(etype="ADJ", tkey=leg_adj.eid_key.values, sign=np.where(leg_adj.direction == "IN", 1, -1), vendor_id=0,
                             unit_cost=np.nan, memo="COUNT")
    # U3: physical shrink the systems never see (indistinguishable from a miscount)
    sh = T.mv[T.mv.movement_type == "shrink"]
    log.add("U3", "TRUTH", "none", "shrink-" + sh.movement_id.astype(str), "movement", sh.movement_id, sh.movement_date,
            [{"sku_id": int(s), "warehouse_id": int(w), "qty": int(abs(q))} for s, w, q in zip(sh.sku_id, sh.warehouse_id, sh.qty_delta)],
            "UNDETECTABLE as a cause; visible as count variance")
    return c, wms_adj, leg_adj


# ------------------------------------------------------------------ sheet writer
def _neighbors(code: str, valid: set) -> set:
    num = code[3:8]
    out = set()
    for i in range(5):
        for dgt in "0123456789":
            if dgt != num[i]:
                out.add(code[:3] + num[:i] + dgt + num[i + 1:] + code[8:])
    for i in range(4):
        out.add(code[:3] + num[:i] + num[i + 1] + num[i] + num[i + 2:] + code[8:])
    return {o for o in out if o in valid and o != code}


def _typo(code: str, key: int, valid: set):
    num = code[3:8]
    for attempt in range(8):
        k = np.array([key + attempt * 7919])
        kind = int(uint(k, "x2t", 0, 2)[0])
        if kind == 0:  # transposed adjacent digits
            i = int(uint(k, "x2i", 0, 3)[0])
            new = code[:3] + num[:i] + num[i + 1] + num[i] + num[i + 2:] + code[8:]
        elif kind == 1 and "0" in num:  # letter O for zero
            new = code[:3] + num.replace("0", "O", 1) + code[8:]
        elif kind == 2 and "1" in num:  # lowercase l for one
            new = code[:3] + num.replace("1", "l", 1) + code[8:]
        else:
            continue
        if new != code and new not in valid:
            return new, kind
    return None


def write_counts(T: Truth, c: pd.DataFrame, log: DefectLog) -> dict:
    sku = T.sku.set_index("sku_id")
    code = sku.sku_code
    valid = set(sku.sku_code)
    bins = bins_table(T).set_index(["sku_id", "warehouse_id"])
    c = c.copy()
    c["sku_code"] = c.sku_id.map(code)
    c["desc"] = c.sku_id.map(sku.description)
    c["cat"] = c.sku_id.map(sku.category_id)
    c["cp"] = c.sku_id.map(sku.case_pack_qty)
    ids = c.count_id.values
    c["counter"] = [COUNTERS[int(w)][int(i)] for w, i in zip(c.wh_id, uint(ids, "ctr", 0, 2))]
    c["w_qty"] = c.true_qty.astype(float)
    c["w_code"] = c.sku_code
    c["w_date"] = c.count_date
    c["w_uom"] = "EA"
    c["note"] = np.where(pick(ids, "note", 0.03), np.array(NOTES)[uint(ids, "notei", 0, len(NOTES) - 1)], "")
    ev = []

    # U1: one branch manager's counts biased +2% for three months
    u1 = (c.wh_id == 2) & (c.counter == COUNTERS[2][0]) & (c.count_date >= U1_MONTHS[0]) & (c.count_date <= U1_MONTHS[1])
    f = c.true_qty * 1.02
    biased = np.floor(f) + (u01(ids, "u1r") < (f - np.floor(f)))
    c.loc[u1, "w_qty"] = biased[u1]
    # X3: cases counted but entered as each
    elig = (c.cp > 1) & (c.true_qty >= c.cp) & ~u1
    hist = (c.count_date <= H0)
    p3 = min(1.0, 0.008 * hist.sum() / max((elig & hist).sum(), 1))
    x3 = elig & pick(ids, "x3", p3)
    c.loc[x3, "w_qty"] = (c.true_qty[x3] // c.cp[x3]).astype(float)
    # X2: SKU typos
    typo_mask = pick(ids, "x2", 0.02) & ~x3
    x2rows = []
    for i in c.index[typo_mask]:
        res = _typo(c.at[i, "sku_code"], int(c.at[i, "count_id"]), valid)
        if res is None:
            continue
        new = res[0]
        cands = _neighbors(new, valid)
        c.at[i, "w_code"] = new
        x2rows.append((i, new, len(cands | {c.at[i, "sku_code"]}) == 1))
    x2 = pd.DataFrame(x2rows, columns=["i", "typed", "recoverable"]).set_index("i") if x2rows else pd.DataFrame(columns=["typed", "recoverable"])
    # U2: two valid SKUs transposed
    u2 = pick(ids, "u2", 0.001) & ~c.index.isin(x2.index) & ~x3
    cand = {k: g.sku_id.values for k, g in c[c.count_date <= H0].groupby(["wh_id", "cat"])}  # frozen-history candidates, so later counts never move an earlier swap
    swap = {}
    for i in c.index[u2]:
        lst = cand[(c.at[i, "wh_id"], c.at[i, "cat"])]
        lst = lst[lst != c.at[i, "sku_id"]]
        if len(lst):
            swap[i] = int(lst[int(uint(np.array([c.at[i, "count_id"]]), "u2s", 0, len(lst) - 1)[0])])
    for i, s in swap.items():
        c.at[i, "w_code"] = code[s]
        c.at[i, "desc"] = sku.description[s]
    # X5: count dated with the wrong month or year
    x5 = pick(ids, "x5", 0.004)
    kind = uint(ids, "x5k", 0, 2)
    d = c.count_date
    nd = np.where(kind == 0, d - pd.to_timedelta(30, unit="D"), np.where(kind == 1, d + pd.to_timedelta(30, unit="D"), d - pd.to_timedelta(365, unit="D")))
    c.loc[x5, "w_date"] = pd.Series(pd.to_datetime(nd), index=c.index)[x5]

    # layout and file writing, one workbook per warehouse-month
    c["file_month"] = c.count_date.dt.strftime("%Y-%m")
    out_rows = {}
    folder = SRC / "spreadsheets" / "count_sheets"
    n_files = 0
    x1_files, x4_files = [], []
    for (wh, mon), g in c.groupby(["wh_id", "file_month"], sort=True):
        fk = np.array([wh * 1000 + int(mon[:4]) % 100 * 12 + int(mon[5:])])
        variant = 0 if u01(fk, "x1") >= 0.35 else int(uint(fk, "x1v", 1, 3)[0])
        hdr = HEADERS[variant]
        dstyle = ["date", "slash", "dmy"][int(uint(fk, "dstyle", 0, 2)[0])] if u01(fk, "dst") > 0.6 else "date"
        wb = Workbook()
        ws = wb.active
        ws.title = "Count"
        wc = T.wh_code[wh]
        ws["A1"] = "Northfield Supply Co. - Cycle Count Sheet"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = f"Branch: {wc} {T.wh.set_index('warehouse_id').name[wh]}"
        ws["A3"] = f"Month: {mon}"
        for j, h in enumerate(hdr, 1):
            ws.cell(row=5, column=j, value=h).font = Font(bold=True)
        r = 6
        rel = f"spreadsheets/count_sheets/{wc}/{mon}_count.xlsx"
        g = g.sort_values(["cat", "w_code"])
        for catid, gg in g.groupby("cat", sort=True):
            ws.cell(row=r, column=1, value=T.cat.set_index("category_id").name[catid].upper())
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(hdr))
            ws.cell(row=r, column=1).font = Font(bold=True)
            r += 1
            first = r
            for i, row in gg.iterrows():
                dv = row.w_date
                dcell = dv.to_pydatetime() if dstyle == "date" else (dv.strftime("%m/%d/%Y") if dstyle == "slash" else dv.strftime("%d-%b-%y"))
                b = bins.bin_new[(row.sku_id, wh)] if (wh == 2 and row.count_date >= DRIFT_DATE) else bins.bin_old[(row.sku_id, wh)]
                vals = [row.w_code, row.desc, b, row.w_uom, int(row.w_qty) if row.w_qty == int(row.w_qty) else row.w_qty,
                        row.counter, dcell, row.note]
                for j, v in enumerate(vals, 1):
                    ws.cell(row=r, column=j, value=v)
                if dstyle == "date":
                    ws.cell(row=r, column=7).number_format = "yyyy-mm-dd"
                out_rows[row.count_id] = (rel, r)
                r += 1
            ws.cell(row=r, column=1, value="Subtotal")
            ws.cell(row=r, column=5, value=f"=SUM(E{first}:E{r - 1})")
            r += 1
            if u01(np.array([catid * 7 + wh]), "blank") < 0.5:
                r += 1
            if u01(np.array([catid * 13 + wh + int(mon[5:])]), "xnote") < 0.15:
                ws.cell(row=r, column=1, value="NOTE: second shift did aisle B")
                r += 1
        ws.cell(row=r + 1, column=1, value="TOTAL COUNTED")
        for j in range(1, len(hdr) + 1):
            ws.column_dimensions[get_column_letter(j)].width = 18
        (folder / wc).mkdir(parents=True, exist_ok=True)
        wb.save(folder / wc / f"{mon}_count.xlsx")
        n_files += 1
        x4_files.append(rel)
        if variant:
            x1_files.append((rel, hdr))
    keyf = lambda idx: [f"{out_rows[c.at[i, 'count_id']][0]}|{out_rows[c.at[i, 'count_id']][1]}" for i in idx]
    log.add("X4", SYS, "count_file", x4_files, "file", x4_files, None, "merged cells, subtotal rows, blank rows and notes inside the data area", "AUTO-strip")
    log.add("X1", SYS, "count_file", [f for f, _ in x1_files], "file", [f for f, _ in x1_files], None, [{"headers": h} for _, h in x1_files], "AUTO-map headers")
    ix = x2.index
    log.add("X2", SYS, "count_row", keyf(ix), "count", c.count_id[ix], c.count_date[ix],
            [{"true_code": c.at[i, "sku_code"], "typed": x2.at[i, "typed"], "recoverable": bool(x2.at[i, "recoverable"])} for i in ix], "AUTO-FIX if unique single edit else REVIEW")
    ix3 = c.index[x3]
    log.add("X3", SYS, "count_row", keyf(ix3), "count", c.count_id[ix3], c.count_date[ix3],
            [{"true_qty": int(c.at[i, "true_qty"]), "written": int(c.at[i, "w_qty"]), "case_pack": int(c.at[i, "cp"])} for i in ix3], "FLAG (plausibility vs system)")
    ix5 = c.index[x5]
    log.add("X5", SYS, "count_row", keyf(ix5), "count", c.count_id[ix5], c.count_date[ix5],
            [{"true_date": str(c.at[i, "count_date"].date()), "written": str(c.at[i, "w_date"].date())} for i in ix5], "FLAG")
    iu1 = c.index[u1]
    log.add("U1", SYS, "count_row", keyf(iu1), "count", c.count_id[iu1], c.count_date[iu1],
            [{"true": int(c.at[i, "true_qty"]), "written": int(c.at[i, "w_qty"])} for i in iu1], "UNDETECTABLE per row (statistical only)")
    iu = list(swap.keys())
    log.add("U2", SYS, "count_row", keyf(iu), "count", c.count_id[iu], c.count_date[iu],
            [{"true_code": c.at[i, "sku_code"], "written": c.at[i, "w_code"]} for i in iu], "UNDETECTABLE at ingestion")
    return {"count_rows": len(c), "count_files": n_files, "x1_files": len(x1_files), "x2": len(ix), "x2_recoverable": int(x2.recoverable.sum()) if len(x2) else 0,
            "x3": int(x3.sum()), "x5": int(x5.sum()), "u1": int(u1.sum()), "u2": len(iu)}


def write_price_overrides(T: Truth, log: DefectLog) -> dict:
    pl = T.pol.merge(T.po[["po_id", "vendor_id", "po_date"]], on="po_id")
    pl = pl[pick(pl.po_line_id.values, "pov", 0.081)].copy()
    sku = T.sku.set_index("sku_id")
    pl["eff"] = pl.po_date - pd.to_timedelta(uint(pl.po_line_id.values, "pove", 1, 14), unit="D")
    pl["entered"] = pl.eff + pd.to_timedelta(uint(pl.po_line_id.values, "povt", 0, 5 * 86400), unit="s")
    cities = vendor_city(T)
    base = pd.DataFrame({"vendor": pl.vendor_id.map(T.vend.set_index("vendor_id").name).values, "item_no": pl.sku_id.map(sku.sku_code).values,
                         "override_cost": pl.unit_cost.values, "effective_date": pl.eff.values, "entered_on": pl.entered.values,
                         "entered_by": np.array(["purch1", "purch2", "buyer_ak"])[uint(pl.po_line_id.values, "povb", 0, 2)], "note": "",
                         "src_key": pl.po_line_id.values, "is_conflict": False})
    cf = pick(pl.po_line_id.values, "x6", 0.015)
    extra = base[cf].copy()
    extra["override_cost"] = (extra.override_cost * (1 + np.where(u01(extra.src_key.values, "x6s") < 0.5, 1, -1) * ufloat(extra.src_key.values, "x6m", 0.03, 0.08))).round(2)
    later = u01(extra.src_key.values, "x6o") < 0.5
    extra["entered_on"] = extra.entered_on + pd.to_timedelta(np.where(later, 1, -1) * uint(extra.src_key.values, "x6t", 3600, 86400), unit="s")
    extra["is_conflict"] = True
    allp = pd.concat([base, extra], ignore_index=True).sort_values(["effective_date", "item_no"])
    allp["month"] = pd.to_datetime(allp.effective_date).dt.strftime("%Y-%m")
    folder = SRC / "spreadsheets" / "price_overrides"
    folder.mkdir(parents=True, exist_ok=True)
    keys = {}
    for mon, g in allp.groupby("month"):
        wb = Workbook()
        ws = wb.active
        ws.title = "Overrides"
        ws["A1"] = "Vendor price overrides (purchasing)"
        ws["A1"].font = Font(bold=True, size=13)
        hdr = ["Vendor", "Item No", "Override Cost", "Effective Date", "Entered On", "Entered By", "Note"]
        for j, h in enumerate(hdr, 1):
            ws.cell(row=3, column=j, value=h).font = Font(bold=True)
        r = 4
        for row in g.itertuples():
            for j, v in enumerate([row.vendor, row.item_no, row.override_cost, pd.Timestamp(row.effective_date).to_pydatetime(),
                                   pd.Timestamp(row.entered_on).to_pydatetime(), row.entered_by, row.note], 1):
                ws.cell(row=r, column=j, value=v)
            ws.cell(row=r, column=4).number_format = "yyyy-mm-dd"
            ws.cell(row=r, column=5).number_format = "yyyy-mm-dd hh:mm"
            keys[(row.src_key, row.is_conflict)] = f"spreadsheets/price_overrides/{mon}_vendor_price_overrides.xlsx|{r}"
            r += 1
        wb.save(folder / f"{mon}_vendor_price_overrides.xlsx")
    ex = allp[allp.is_conflict]
    orig = base.set_index("src_key")
    later_flag = ex.entered_on.values > orig.entered_on.reindex(ex.src_key).values
    log.add("X6", SYS, "price_row", [keys[(s, True)] for s in ex.src_key], "po_line", ex.src_key, ex.effective_date,
            [{"correct_cost": float(orig.override_cost[s]), "conflicting_cost": float(cst), "conflict_entered_later": bool(lf)}
             for s, cst, lf in zip(ex.src_key, ex.override_cost, later_flag)], "FLAG (documented latest-wins rule)")
    return {"price_rows": len(allp), "x6": len(ex), "x6_conflict_later": int(later_flag.sum())}
