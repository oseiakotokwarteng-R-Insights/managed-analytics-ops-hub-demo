"""Daily simulation of the hidden 'true' business: demand, fulfillment/backorders, replenishment,
inter-warehouse transfers, shrink, lifecycle, scenarios S1/S5, and truth freight. Per-day RNG streams make
the run deterministic and resumable (the live clock continues from a saved state)."""
from __future__ import annotations

import math
import pickle
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

from . import config as C
from .masters import build_masters
from .sources.common import uint

MOVE_TYPES = ["receipt", "ship", "transfer_out", "transfer_in", "shrink", "scenario_loss", "disposal"]
REF_TYPES = ["po_line", "order_line", "transfer", "none"]
CARRIERS = ["CARRIER_A", "CARRIER_B", "OWN_FLEET", "WILL_CALL", "VENDOR_DELIVERED", "OWN_PICKUP"]
CA, CB, OWN, WC, VD, OP = range(6)
EPOCH_ORD = date(1970, 1, 1).toordinal()


class Recorder:
    def __init__(self):
        self.t = defaultdict(lambda: defaultdict(list))

    def add(self, table, **cols):
        n = len(next(iter(cols.values())))
        if n == 0:
            return
        for k, v in cols.items():
            self.t[table][k].append(np.asarray(v))

    def frame(self, table):
        import pandas as pd
        cols = self.t.get(table)
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame({k: np.concatenate(v) for k, v in cols.items()})


class Sim:
    def __init__(self, M=None, rec: Recorder | None = None):
        self.M = M or build_masters()
        self.rec = rec if rec is not None else Recorder()
        self._calibrate()
        self._prep_calendar()
        self._init_state()

    # ------------------------------------------------------------------ setup
    def _prep_calendar(self):
        cal = self.M.cal
        n = len(cal.dates)
        nxt = np.empty(n, dtype=np.int64)
        prv = np.empty(n, dtype=np.int64)
        cur = cal.ordinals[-1] + 30
        for i in range(n - 1, -1, -1):
            if cal.is_recv[i]:
                cur = cal.ordinals[i]
            nxt[i] = cur
        cur = cal.ordinals[0] - 30
        for i in range(n):
            if cal.is_recv[i]:
                cur = cal.ordinals[i]
            prv[i] = cur
        self.next_recv, self.prev_recv = nxt, prv

    def nr(self, ords):
        return self.next_recv[np.clip(np.asarray(ords) - self.M.cal.base_ord, 0, len(self.next_recv) - 1)]

    def pr(self, ords):
        return self.prev_recv[np.clip(np.asarray(ords) - self.M.cal.base_ord, 0, len(self.prev_recv) - 1)]

    def lam_day(self, di, d, scenarios=True):
        M, cal = self.M, self.M.cal
        if not cal.is_open[di]:
            return np.zeros(M.n_pair)
        do = d.toordinal()
        season = M.season[:, min(d.timetuple().tm_yday, 367) - 1][M.sku_cat]
        growth = (1 + C.ANNUAL_GROWTH) ** ((do - C.WINDOW_START.toordinal()) / 365.0)
        life = np.clip((do - M.sku_intro) / M.sku_ramp, 0, 1) * np.clip(1 - (do - M.sku_disc) / M.sku_fade, 0, 1)
        lam = M.pair_lam_base * season[M.pair_sku] * growth * C.DOW_FACTOR[int(cal.dow[di])] * life[M.pair_sku]
        if scenarios and C.S5_START <= d <= C.S5_END:
            lam[M.s5_pairs] *= C.S5_MULT
        return lam

    def _calibrate(self):
        M, cal = self.M, self.M.cal
        d0, d1 = C.WINDOW_START, C.HISTORY_END
        tot_lines = tot_rev = 0.0
        for di, d in enumerate(cal.dates):
            if d < d0 or d > d1:
                continue
            lam = self.lam_day(di, d)
            tot_lines += lam.sum()
            tot_rev += (lam * M.sku_mean_qty[M.pair_sku] * M.sku_price0[M.pair_sku]).sum() * cal.price_index[di] * 0.90
        k = C.TARGET_LINES_WINDOW / tot_lines
        M.pair_lam_base = M.pair_lam_base * k
        days = (d1 - d0).days + 1
        annual = tot_rev * k * 365.0 / days
        self.price_scale = C.TARGET_ANNUAL_REVENUE / (annual * C.EXPECTED_FILL)
        self.line_scale = k

    def _per_pair_static(self):
        M = self.M
        sk = M.pair_sku
        self.p_vendor = M.sku_vendor[sk]
        self.p_lt = M.vend_quoted_lt[self.p_vendor] + 2 + 3.5 * M.vend_cycle[self.p_vendor]
        self.p_z = np.array([C.CLASS_Z[k] for k in M.sku_class])[sk]
        self.p_cover = np.array([C.CLASS_COVER_DAYS[k] for k in M.sku_class])[sk]
        self.p_meanq = M.sku_mean_qty[sk]
        self.p_cp = M.sku_case_pack[sk]
        self.p_wt = M.sku_weight[sk]

    def reorder_params(self):
        ew = self.ewma
        rop = np.ceil(ew * self.p_lt + self.p_z * np.sqrt(self.p_lt * ew * self.p_meanq * 1.8))
        rop = np.maximum(rop, 1)
        S = rop + np.maximum(self.p_cover * ew, self.p_cp)
        return rop, S

    def _init_state(self):
        M = self.M
        P = M.n_pair
        self._per_pair_static()
        rng = np.random.default_rng([C.SEED, 2])
        self.cur_ord = C.WARMUP_START.toordinal() - 1
        self.next_ids = dict(order=1, line=1, po=1, po_line=1, transfer=1, move=1, ship=1, charge=1)
        self.backlog = {}
        self.arr_po = defaultdict(list)
        self.arr_tr = defaultdict(list)
        self.blocked = np.zeros(P, dtype=bool)
        self.backlog_qty = np.zeros(P, dtype=np.int64)
        self.onorder = np.zeros(P, dtype=np.int64)
        d0 = C.WARMUP_START
        di0 = (d0 - M.cal.start).days
        lam0 = self.lam_day(di0 + 3, d0 + timedelta(days=3), scenarios=False)  # a Monday
        full = M.pair_lam_base * M.sku_mean_qty[M.pair_sku] * 0.86
        live = (M.sku_intro[M.pair_sku] <= d0.toordinal()) & (M.sku_disc[M.pair_sku] > d0.toordinal())
        self.ewma = np.where(live, np.maximum(lam0 * 0.86 * self.p_meanq, 0.3 * full), 0.0)
        rop, S = self.reorder_params()
        self.onhand = np.where(live, np.round(S * rng.uniform(0.5, 1.0, P)), 0).astype(np.int64)
        # initial stocking POs for new launches / successors (arrive just before their intro date)
        intro = M.sku_intro[M.pair_sku]
        need = np.nonzero((M.sku_kind[M.pair_sku] == "new_launch") | (M.sku_kind[M.pair_sku] == "successor"))[0]
        self.intro_days = defaultdict(list)
        if len(need):
            arr = self.pr(intro[need] - 3)
            qty = np.ceil(np.maximum(2 * self.p_cp[need], 35 * full[need]) / self.p_cp[need]) * self.p_cp[need]
            self._create_pos(need, qty.astype(np.int64), arr, rng, initial=True)
            for p, o in zip(need, intro[need]):
                self.intro_days[int(o)].append(int(p))
        self.intro_days = {k: np.array(v) for k, v in self.intro_days.items()}
        self.full_rate = full
        self.disp_cut = M.sku_disc[M.pair_sku] + M.sku_fade[M.pair_sku] + 15

    # ------------------------------------------------------------------ helpers
    def _id(self, name, n):
        a = np.arange(self.next_ids[name], self.next_ids[name] + n, dtype=np.int64)
        self.next_ids[name] += n
        return a

    def _ts(self, di, wh_idx, local_sec):
        base = (self.M.cal.ordinals[di] - EPOCH_ORD) * 86400
        return base + np.asarray(local_sec, dtype=np.int64) - self.M.utc_offset_s[di, wh_idx]

    def _move(self, di, d, pairs, qty, mtype, ref_type, ref_ids, local_sec):
        pairs = np.asarray(pairs)
        n = len(pairs)
        if n == 0:
            return
        M = self.M
        wh = M.pair_wh[pairs]
        self.rec.add("move", movement_id=self._id("move", n), date_ord=np.full(n, d.toordinal()),
                     ts_utc=self._ts(di, wh, local_sec), sku_idx=M.pair_sku[pairs], wh_idx=wh, qty=np.asarray(qty, dtype=np.int64),
                     mtype=np.full(n, MOVE_TYPES.index(mtype)), ref_type=np.full(n, REF_TYPES.index(ref_type)),
                     ref_id=np.asarray(ref_ids, dtype=np.int64))

    # ------------------------------------------------------------------ replenishment
    def _create_pos(self, pairs, qty, arrival_ord, rng, initial=False, d=None):
        M = self.M
        pairs = np.asarray(pairs)
        vend = self.p_vendor[pairs]
        wh = M.pair_wh[pairs]
        key = vend.astype(np.int64) * 100 + wh * 1 + arrival_ord * 100000 if initial else vend.astype(np.int64) * 100 + wh
        uk, first, inv = np.unique(key, return_index=True, return_inverse=True)
        n_po = len(uk)
        po_ids = self._id("po", n_po)
        pv, pw = vend[first], wh[first]
        quoted = M.vend_quoted_lt[pv]
        if initial:
            arr_po = arrival_ord[first]
            promised = arr_po
            po_ord = arr_po - quoted - 2
        else:
            po_ord = np.full(n_po, d.toordinal())
            promised = self.nr(po_ord + quoted)
            late = rng.random(n_po) < M.vend_late_prob[pv]
            delay = np.where(late, 1 + rng.geometric(1 / 3.5, size=n_po) - 1, 0)
            arr_po = self.nr(po_ord + quoted + delay)
        line_po = po_ids[inv]
        short = rng.random(len(pairs)) < 0.05
        recv = np.where(short, np.floor(qty * rng.uniform(0.5, 0.95, len(pairs))), qty).astype(np.int64)
        line_ids = self._id("po_line", len(pairs))
        di_rec = np.clip(po_ord - M.cal.base_ord, 0, len(M.cal.dates) - 1)
        pidx = M.cal.price_index[di_rec][inv]
        cost = np.round(M.sku_cost0[M.pair_sku[pairs]] * self.price_scale * pidx * (1 + rng.normal(0, 0.01, len(pairs))), 2)
        self.rec.add("po", po_id=po_ids, vendor_idx=pv, wh_idx=pw, po_ord=po_ord, promised_ord=promised, received_ord=arr_po)
        self.rec.add("po_line", po_line_id=line_ids, po_id=line_po, sku_idx=M.pair_sku[pairs], qty_ordered=qty,
                     qty_received=recv, unit_cost=cost, received_ord=arr_po[inv])
        np.add.at(self.onorder, pairs, qty)
        line_arr = arr_po[inv]
        for ao in np.unique(line_arr):
            m = line_arr == ao
            self.arr_po[int(ao)].append((line_ids[m], pairs[m], qty[m], recv[m], line_po[m]))

    def _replenish(self, d, di, rng):
        M, cal = self.M, self.M.cal
        if not cal.is_recv[di]:
            return
        do = d.toordinal()
        rop, S = self.reorder_params()
        sk = M.pair_sku
        orderable = (do < M.sku_disc[sk]) & (do >= M.sku_intro[sk]) & ~self.blocked
        pos = self.onhand + self.onorder - self.backlog_qty
        trig = orderable & (pos <= rop)
        # transfers from the hub (spokes only), any receiving day
        cand = np.nonzero(trig & (M.pair_wh > 0))[0]
        if len(cand):
            cand = cand[rng.random(len(cand)) < 0.35]
        t_pairs, t_from, t_qty = [], [], []
        for p in cand:
            hp = M.hub_pair_of_sku[sk[p]]
            if self.blocked[hp]:
                continue
            q = int(math.ceil(max(S[p] - pos[p], 1) / self.p_cp[p]) * self.p_cp[p])
            if self.onhand[hp] - q >= 1.2 * rop[hp] and q > 0:
                self.onhand[hp] -= q
                self.onorder[p] += q
                pos[p] += q
                t_pairs.append(p)
                t_from.append(hp)
                t_qty.append(q)
        if t_pairs:
            t_pairs, t_from, t_qty = np.array(t_pairs), np.array(t_from), np.array(t_qty)
            tids = self._id("transfer", len(t_pairs))
            in_ord = self.nr(do + M.wh_transfer_days[M.pair_wh[t_pairs]])
            self._move(di, d, t_from, -t_qty, "transfer_out", "transfer", tids, rng.integers(8 * 3600, 15 * 3600, len(tids)))
            self.rec.add("transfer", transfer_id=tids, sku_idx=sk[t_pairs], from_wh_idx=np.zeros(len(tids), dtype=int),
                         to_wh_idx=M.pair_wh[t_pairs], qty=t_qty, out_ord=np.full(len(tids), do), in_ord=in_ord)
            for ao in np.unique(in_ord):
                m = in_ord == ao
                self.arr_tr[int(ao)].append((tids[m], t_pairs[m], t_qty[m]))
        # purchase orders on each vendor's order day
        week = (do - 1) // 7
        cycle_ok = (week % M.vend_cycle == M.vend_offset)[self.p_vendor]
        vmask = M.vend_dow_mask[self.p_vendor, int(cal.dow[di])] & cycle_ok
        trig2 = orderable & vmask & (pos <= rop)
        pairs = np.nonzero(trig2)[0]
        if len(pairs):
            need = np.maximum(S[pairs] - pos[pairs], 1)
            qty = (np.ceil(need / self.p_cp[pairs]) * self.p_cp[pairs]).astype(np.int64)
            self._create_pos(pairs, qty, None, rng, d=d)

    # ------------------------------------------------------------------ freight
    def _charges(self, ship_ids, carrier, weight, miles, rng):
        n = len(ship_ids)
        rows = defaultdict(list)

        def add(mask, ctype, amount):
            if mask.any():
                rows["shipment_id"].append(ship_ids[mask])
                rows["charge_type"].append(np.full(mask.sum(), ctype, dtype=object))
                rows["amount"].append(np.round(amount[mask], 2))
        a = carrier == CA
        tier = np.where(weight < 1000, 1.0, np.where(weight < 5000, 0.8, 0.65))
        ltl = np.maximum(95.0, weight / 100.0 * (10 + 0.018 * miles) * tier * rng.uniform(0.9, 1.1, n))
        truckload = (350 + 2.1 * miles) * rng.uniform(0.9, 1.1, n)  # full loads are priced per mile, not per cwt
        base_a = np.where(weight > 10000, truckload, ltl)
        add(a, "linehaul", base_a)
        add(a, "fuel_surcharge", base_a * rng.uniform(0.17, 0.21, n))
        add(a & (rng.random(n) < 0.10), "liftgate", np.full(n, 68.0))
        add(a & (rng.random(n) < 0.04), "residential", np.full(n, 95.0))
        add(a & (rng.random(n) < 0.03), "limited_access", np.full(n, 75.0))
        add(a & (rng.random(n) < 0.02), "detention", np.full(n, 120.0))
        b = carrier == CB
        base_b = 9.5 + 0.55 * weight * (1 + miles / 600.0)
        add(b, "base", base_b)
        add(b, "fuel_surcharge", base_b * 0.14)
        add(b & (rng.random(n) < 0.20), "residential", np.full(n, 5.8))
        add(b & (weight > 50), "oversize", np.full(n, 22.0))
        if not rows:
            return
        n_rows = sum(len(x) for x in rows["shipment_id"])
        self.rec.add("charge", charge_id=self._id("charge", n_rows), shipment_id=np.concatenate(rows["shipment_id"]),
                     charge_type=np.concatenate(rows["charge_type"]), amount=np.concatenate(rows["amount"]))

    def _transit(self, carrier, miles):
        q = np.where(carrier == CA, np.ceil(miles / 450.0) + 1, np.where(carrier == CB, np.ceil(miles / 500.0) + 1,
                     np.where(carrier == OWN, np.where(miles > 20, 1, 0), np.where(carrier == WC, 0, np.ceil(miles / 450.0) + 1))))
        return q.astype(np.int64)

    def _outbound_shipments(self, d, di, order_ids, wh_idx, mode, miles, weight, ship_sec, rng):
        n = len(order_ids)
        if n == 0:
            return
        do = d.toordinal()
        q = self._transit(mode, miles)
        promised = np.where(mode == WC, do, self.nr(do + q))
        delay = np.where(mode == CA, np.where(rng.random(n) < 0.09, rng.integers(1, 4, n), 0),
                         np.where(mode == CB, np.where(rng.random(n) < 0.05, rng.integers(1, 3, n), 0),
                                  np.where(mode == OWN, np.where(rng.random(n) < 0.04, 1, 0), 0)))
        delivered = np.where(mode == WC, do, self.nr(promised + delay))
        sid = self._id("ship", n)
        self.rec.add("ship", shipment_id=sid, direction=np.zeros(n, dtype=int), carrier=mode, ref_type=np.zeros(n, dtype=int),
                     ref_id=order_ids, wh_idx=wh_idx, ship_ord=np.full(n, do), ship_ts=self._ts(di, wh_idx, ship_sec),
                     weight_lb=np.round(weight, 1), pieces=np.maximum(1, np.ceil(weight / 60.0)).astype(int),
                     miles=np.round(miles, 1), quoted_transit_days=q, promised_ord=promised, delivered_ord=delivered)
        self._charges(sid, mode, weight, miles, rng)

    def _inbound_shipments(self, d, di, po_ids, pairs, q_rcv, rng):
        M = self.M
        uid, first, inv = np.unique(po_ids, return_index=True, return_inverse=True)
        n = len(uid)
        weight = np.bincount(inv, weights=q_rcv * self.p_wt[pairs], minlength=n)
        vend = self.p_vendor[pairs[first]]
        wh = M.pair_wh[pairs[first]]
        miles = np.clip(M.vend_dist_miles[vend] + rng.normal(0, 20, n), 15, None)
        u = rng.random(n)
        light = weight < 100
        mode = np.where(light, np.where(u < 0.30, CB, VD), np.where(u < 0.15, CA, np.where(u < 0.90, VD, OP)))
        do = d.toordinal()
        q = self._transit(mode, miles)
        delay = np.where(mode == CA, np.where(rng.random(n) < 0.09, rng.integers(1, 4, n), 0),
                         np.where(mode == CB, np.where(rng.random(n) < 0.05, rng.integers(1, 3, n), 0), 0))
        ship_ord = self.pr(do - q - delay)
        sid = self._id("ship", n)
        self.rec.add("ship", shipment_id=sid, direction=np.ones(n, dtype=int), carrier=mode, ref_type=np.ones(n, dtype=int),
                     ref_id=uid, wh_idx=wh, ship_ord=ship_ord, ship_ts=self._ts(di, wh, np.full(n, 9 * 3600)) - (do - ship_ord) * 86400,
                     weight_lb=np.round(weight, 1), pieces=np.maximum(1, np.ceil(weight / 60.0)).astype(int),
                     miles=np.round(miles, 1), quoted_transit_days=q, promised_ord=ship_ord + q, delivered_ord=np.full(n, do))
        self._charges(sid, mode, weight, miles, rng)

    # ------------------------------------------------------------------ demand and fulfillment
    def _customers_for(self, do, w, t, rng, k):
        M = self.M
        ok = (M.cust_wh == w) & (M.cust_start <= do) & (M.cust_end >= do)
        pool = np.nonzero(ok & (M.cust_type == t))[0]
        if len(pool) == 0:
            pool = np.nonzero(ok)[0]
        if len(pool) == 0:
            pool = np.nonzero(M.cust_wh == w)[0]
        cw = np.cumsum(M.cust_size[pool])
        return pool[np.minimum(np.searchsorted(cw / cw[-1], rng.random(k)), len(pool) - 1)]

    def _clear_backlog(self, d, di, rng):
        M = self.M
        bk_pairs, bk_qty, bk_line, bk_order, bk_mode, bk_miles, bk_wh = [], [], [], [], [], [], []
        for p in sorted(self.backlog):
            if self.onhand[p] <= 0:
                continue
            q = self.backlog[p]
            while q and self.onhand[p] > 0:
                ent = q[0]
                s = min(ent[2], int(self.onhand[p]))
                ent[2] -= s
                self.onhand[p] -= s
                self.backlog_qty[p] -= s
                bk_pairs.append(p), bk_qty.append(s), bk_line.append(ent[0]), bk_order.append(ent[1])
                bk_mode.append(ent[3]), bk_miles.append(ent[4]), bk_wh.append(M.pair_wh[p])
                if ent[2] == 0:
                    q.pop(0)
            if not q:
                del self.backlog[p]
        if not bk_pairs:
            return
        bp, bq = np.array(bk_pairs), np.array(bk_qty)
        bsec = rng.integers(8 * 3600, 15 * 3600, len(bp))
        self._move(di, d, bp, -bq, "ship", "order_line", np.array(bk_line), bsec)
        uo, f, iv = np.unique(np.array(bk_order), return_index=True, return_inverse=True)
        wgt = np.bincount(iv, weights=bq * self.p_wt[bp], minlength=len(uo))
        self._outbound_shipments(d, di, uo, np.array(bk_wh)[f], np.array(bk_mode)[f], np.array(bk_miles)[f], wgt, bsec[f], rng)

    def _demand(self, d, di, rng):
        M = self.M
        P = M.n_pair
        do = d.toordinal()
        lam = self.lam_day(di, d)
        n_lines = rng.poisson(lam * rng.gamma(2.0, 0.5, size=P))
        pair = np.repeat(np.arange(P), n_lines)
        L = len(pair)
        units_today = np.zeros(P)
        self._clear_backlog(d, di, rng)
        if L == 0:
            return units_today
        sku = M.pair_sku[pair]
        qty = np.maximum(1, np.round(rng.lognormal(np.log(M.sku_mean_qty[sku]) - 0.245, 0.7))).astype(np.int64)
        wh = M.pair_wh[pair]
        order_global = np.empty(L, dtype=np.int64)
        base_oid = self.next_ids["order"]
        cust_of_order, wh_of_order, first_line = [], [], []
        offset = 0
        for w in range(M.n_wh):
            idx = np.nonzero(wh == w)[0]
            m = len(idx)
            if m == 0:
                continue
            idx = idx[rng.permutation(m)]
            sizes = rng.geometric(1 / C.MEAN_LINES_PER_ORDER, size=m)
            cs = np.cumsum(sizes)
            k = int(np.searchsorted(cs, m)) + 1
            bounds = np.minimum(cs[:k], m)
            sizes = np.diff(np.concatenate([[0], bounds]))
            starts = bounds - sizes
            order_global[idx] = offset + np.repeat(np.arange(k), sizes)
            catf = M.sku_cat[sku[idx[starts]]]
            u = rng.random(k)
            tpe = np.minimum((u[:, None] > M.type_given_cat_cum[catf]).sum(axis=1), len(C.CUSTOMER_TYPES) - 1)
            cust = np.empty(k, dtype=np.int64)
            for t in range(len(C.CUSTOMER_TYPES)):
                mt = tpe == t
                if mt.any():
                    cust[mt] = self._customers_for(do, w, t, rng, int(mt.sum()))
            cust_of_order.append(cust)
            wh_of_order.append(np.full(k, w))
            offset += k
        cust_of_order = np.concatenate(cust_of_order)
        wh_of_order = np.concatenate(wh_of_order)
        n_orders = offset
        # merge duplicate SKUs inside an order
        key = order_global * M.n_pair + pair
        _, keep, inv = np.unique(key, return_index=True, return_inverse=True)
        qty_m = np.bincount(inv, weights=qty).astype(np.int64)
        pair, order_global, qty = pair[keep], order_global[keep], qty_m
        L = len(pair)
        sku = M.pair_sku[pair]
        order_ids = base_oid + np.arange(n_orders, dtype=np.int64)
        self.next_ids["order"] += n_orders
        line_ids = self._id("line", L)
        # order attributes
        wt_line = qty * self.p_wt[pair]
        o_weight = np.bincount(order_global, weights=wt_line, minlength=n_orders)
        o_miles = M.cust_dist_miles[cust_of_order]
        wc = rng.random(n_orders) < M.cust_willcall[cust_of_order]
        mode = np.full(n_orders, OWN)
        u1, u2, u3 = rng.random(n_orders), rng.random(n_orders), rng.random(n_orders)
        ltl = ((o_weight > 1500) & (u1 < 0.35)) | ((o_weight > 400) & (o_weight <= 1500) & (u1 < 0.10)) | ((o_miles > 180) & (u2 < 0.5))
        parcel = (o_weight <= 70) & (o_miles > 15) & (u3 < 0.45)
        mode[parcel] = CB
        mode[ltl] = CA
        mode[wc] = WC
        o_sec = (7 * 3600 + rng.beta(2.2, 2.6, n_orders) * 10 * 3600).astype(np.int64)
        price = np.round(M.sku_price0[sku] * self.price_scale * M.cal.price_index[di] * (1 - M.cust_discount[cust_of_order][order_global]), 2)
        line_no = np.zeros(L, dtype=np.int64)
        _, cnt = np.unique(order_global, return_counts=True)
        # line numbers within order (lines are sorted by order then pair)
        starts = np.concatenate([[0], np.cumsum(cnt)[:-1]])
        line_no = np.arange(L) - np.repeat(starts, cnt) + 1
        self.rec.add("order", order_id=order_ids, customer_idx=cust_of_order, wh_idx=wh_of_order, date_ord=np.full(n_orders, do),
                     ts_utc=self._ts(di, wh_of_order, o_sec), delivery_mode=mode, weight_lb=np.round(o_weight, 1))
        self.rec.add("line", line_id=line_ids, order_id=order_ids[order_global], line_no=line_no, sku_idx=sku, qty_ordered=qty,
                     unit_price=price, date_ord=np.full(L, do))
        units_today = np.bincount(pair, weights=qty, minlength=P).astype(float)
        # new lines: allocate stock in line order within each pair (backlog was cleared first)
        srt = np.argsort(pair, kind="stable")
        p_s, q_s = pair[srt], qty[srt]
        cs = np.cumsum(q_s)
        grp = np.concatenate([[True], p_s[1:] != p_s[:-1]])
        gsz = np.diff(np.concatenate([np.nonzero(grp)[0], [len(p_s)]]))
        before = cs - q_s - np.repeat((cs - q_s)[grp], gsz)
        ship_s = np.clip(self.onhand[p_s] - before, 0, q_s)
        ship = np.empty(L, dtype=np.int64)
        ship[srt] = ship_s
        self.onhand -= np.bincount(pair, weights=ship, minlength=P).astype(np.int64)
        sh = ship > 0
        if sh.any():
            o_s = o_sec[order_global[sh]]
            raw = o_s + rng.integers(600, 14400, int(sh.sum()))
            cap = 17 * 3600 + 1800
            ssec = np.where(raw > cap, np.maximum(cap - uint(line_ids[sh], "shipcap", 0, 3 * 3600), o_s + 600), raw)
            self._move(di, d, pair[sh], -ship[sh], "ship", "order_line", line_ids[sh], ssec)
            og = order_global[sh]
            uo, f, iv = np.unique(og, return_index=True, return_inverse=True)
            wgt = np.bincount(iv, weights=ship[sh] * self.p_wt[pair[sh]], minlength=len(uo))
            self._outbound_shipments(d, di, order_ids[uo], wh_of_order[uo], mode[uo], o_miles[uo], wgt, ssec[f], rng)
        un = np.nonzero(ship < qty)[0]
        for i in un:
            rem = int(qty[i] - ship[i])
            o = order_global[i]
            self.backlog.setdefault(int(pair[i]), []).append([int(line_ids[i]), int(order_ids[o]), rem, int(mode[o]), float(o_miles[o])])
            self.backlog_qty[pair[i]] += rem
        return units_today

    # ------------------------------------------------------------------ daily step
    def step(self, d: date):
        M, cal = self.M, self.M.cal
        do = d.toordinal()
        di = do - cal.base_ord
        assert do == self.cur_ord + 1, "days must be stepped in order"
        rng = np.random.default_rng([C.SEED, 1, do])
        P = M.n_pair
        # arrivals
        if cal.is_recv[di]:
            for line_ids, pairs, q_ord, q_rcv, po_ids in self.arr_po.pop(do, []):
                self.onhand += np.bincount(pairs, weights=q_rcv, minlength=P).astype(np.int64)
                self.onorder -= np.bincount(pairs, weights=q_ord, minlength=P).astype(np.int64)
                m = q_rcv > 0
                self._move(di, d, pairs[m], q_rcv[m], "receipt", "po_line", line_ids[m], rng.integers(7 * 3600, 15 * 3600, int(m.sum())))
                self._inbound_shipments(d, di, po_ids, pairs, q_rcv, rng)
            for tids, pairs, q in self.arr_tr.pop(do, []):
                self.onhand += np.bincount(pairs, weights=q, minlength=P).astype(np.int64)
                self.onorder -= np.bincount(pairs, weights=q, minlength=P).astype(np.int64)
                self._move(di, d, pairs, q, "transfer_in", "transfer", tids, rng.integers(7 * 3600, 15 * 3600, len(tids)))
        # new-launch forecast seeding
        if do in self.intro_days:
            ps = self.intro_days[do]
            self.ewma[ps] = 0.6 * self.full_rate[ps]
        # scenario S1: unrecorded physical loss at WH-05 (book keeps showing stock); no replenishment until discovered
        if d == C.S1_START:
            ps = M.s1_pairs[self.onhand[M.s1_pairs] > 0]
            self._move(di, d, ps, -self.onhand[ps], "scenario_loss", "none", np.zeros(len(ps), dtype=np.int64),
                       rng.integers(8 * 3600, 16 * 3600, len(ps)))
            self.onhand[ps] = 0
            self.blocked[M.s1_pairs] = True
        if d == C.S1_DISCOVERED:
            self.blocked[M.s1_pairs] = False
        units = np.zeros(P)
        if cal.is_open[di]:
            units = self._demand(d, di, rng)
            sh = (rng.random(P) < C.SHRINK_DAILY_PROB) & (self.onhand > 0)
            ps = np.nonzero(sh)[0]
            if len(ps):
                loss = np.maximum(1, np.round(self.onhand[ps] * rng.uniform(0.01, 0.06, len(ps)))).astype(np.int64)
                loss = np.minimum(loss, self.onhand[ps])
                self.onhand[ps] -= loss
                self._move(di, d, ps, -loss, "shrink", "none", np.zeros(len(ps), dtype=np.int64), rng.integers(8 * 3600, 17 * 3600, len(ps)))
        self.ewma = (1 - C.EWMA_ALPHA) * self.ewma + C.EWMA_ALPHA * units
        # disposal of discontinued stock
        dm = (do >= self.disp_cut) & (self.onhand > 0) & cal.is_recv[di]
        ps = np.nonzero(dm)[0]
        if len(ps):
            self._move(di, d, ps, -self.onhand[ps], "disposal", "none", np.zeros(len(ps), dtype=np.int64), rng.integers(8 * 3600, 16 * 3600, len(ps)))
            self.onhand[ps] = 0
        self._replenish(d, di, rng)
        if d >= C.WINDOW_START:
            self.rec.add("snap", date_ord=np.array([do]), onhand=self.onhand.astype(np.int32)[None, :],
                         backlog=self.backlog_qty.astype(np.int32)[None, :], on_order=self.onorder.astype(np.int32)[None, :])
        elif d == C.WINDOW_START - timedelta(days=1):
            self.rec.add("opening", onhand=self.onhand.astype(np.int32)[None, :])
        self.cur_ord = do

    def run(self, start: date, end: date):
        d = start
        while d <= end:
            self.step(d)
            d += timedelta(days=1)

    # ------------------------------------------------------------------ persistence (live clock)
    def save_state(self, path):
        keys = ["cur_ord", "next_ids", "backlog", "blocked", "backlog_qty", "onorder", "ewma", "onhand", "intro_days", "full_rate"]
        st = {k: getattr(self, k) for k in keys}
        st["arr_po"] = dict(self.arr_po)
        st["arr_tr"] = dict(self.arr_tr)
        with open(path, "wb") as f:
            pickle.dump(st, f)

    @classmethod
    def load_state(cls, path, rec=None):
        s = cls(rec=Recorder())  # throwaway recorder: initial stocking POs were already recorded in the original run
        with open(path, "rb") as f:
            st = pickle.load(f)
        for k, v in st.items():
            if k in ("arr_po", "arr_tr"):
                v = defaultdict(list, v)
            setattr(s, k, v)
        s.rec = rec if rec is not None else Recorder()
        return s
