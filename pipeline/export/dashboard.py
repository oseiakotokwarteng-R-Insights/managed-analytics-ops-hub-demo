"""Exports the marts to the static JSON the dashboard reads.  Usage: python -m pipeline.export.dashboard

Reads only the warehouse, never the generator's answer key. Only aggregated marts, the review-queue summary and per-SKU stock histories are published; raw rows and the answer key are not.
Output: dashboard/data/*.json and dashboard/data/sku/<item>.json"""
from __future__ import annotations

import json
import math
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .. import config as cfg

OUT = cfg.ROOT / "dashboard" / "data"
CONF = {"verified": 0, "carried": 1, "suspect": 2}
RISK = {"ok": 0, "at_risk": 1, "out_of_stock": 2, "low_demand": 3}


def clean(v):
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return None if pd.isna(v) else pd.Timestamp(v).date().isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(v) or math.isinf(v) else (int(v) if float(v).is_integer() and abs(v) < 1e12 else round(float(v), 4))
    if v is pd.NA or v is pd.NaT:
        return None
    return v


def table(con, sql, params=None):
    df = con.execute(sql, params or []).fetchdf()
    return [{k: clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def write(name, obj):
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return p.stat().st_size


def write_live(clock, runs):
    """live.json: where the live clock stands and how the recent nightly runs went (absent when the dashboard is a static snapshot)."""
    if not clock:
        return
    sim, end = date.fromisoformat(clock["sim_date"]), date.fromisoformat(clock["history_end"])
    write("live.json", {"sim_date": clock["sim_date"], "history_end": clock["history_end"], "days_live": (sim - end).days, "launch_real_date": clock["launch_real_date"],
                        "last_tick_utc": clock.get("last_tick_utc"), "runs": runs, "sla_minutes": 30})


def main():
    shutil.rmtree(OUT / "sku", ignore_errors=True)  # everything else is overwritten; scorecard.json and live.json belong to other writers
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(cfg.WAREHOUSE), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    as_of = con.execute("select max(local_date) from marts.mart_stock_daily").fetchone()[0]
    d0 = con.execute("select min(local_date) from marts.mart_stock_daily").fetchone()[0]
    whs = table(con, "select wh_code, name, city, system_of_record from core.dim_warehouse order by 1")
    wh_codes = [w["wh_code"] for w in whs]
    sizes = {}

    # ----------------------------------------------------------------------------------------------------------------------------- stock
    stock = {"as_of": as_of.isoformat()}
    stock["by_wh"] = table(con, """
        select c.wh_code, w.name, w.system_of_record, count(*) as pairs, sum(est_on_hand) filter (where est_on_hand > 0) as est_units, sum(est_on_hand * std_cost) filter (where est_on_hand > 0) as est_value,
               sum(book_recorded_qty * std_cost) filter (where book_recorded_qty > 0) as recorded_value,
               avg((confidence = 'suspect')::int) as suspect_share, avg((confidence = 'verified')::int) as verified_share, avg(days_since_anchor) as avg_days_since_count,
               count(*) filter (where risk = 'at_risk') as at_risk, count(*) filter (where risk = 'out_of_stock') as out_of_stock,
               sum(available_to_promise) filter (where available_to_promise > 0) as atp_units
        from marts.mart_stock_current c join core.dim_warehouse w using (wh_code) group by 1, 2, 3 order by 1""")
    stock["by_category"] = table(con, """
        select category, count(*) as pairs, sum(est_on_hand * std_cost) filter (where est_on_hand > 0) as est_value, count(*) filter (where risk in ('at_risk', 'out_of_stock')) as at_risk
        from marts.mart_stock_current group by 1 order by 3 desc""")
    stock["confidence_mix"] = table(con, "select confidence, count(*) as pairs from marts.mart_stock_current group by 1 order by 1")
    stock["count_accuracy"] = table(con, """select wh_code, month, items_counted, exact_rate, net_variance_value, abs_variance_value
                                            from marts.mart_count_accuracy where month >= (select max(month) from marts.mart_count_accuracy) - interval 17 month order by wh_code, month""")
    stock["biggest_gaps"] = table(con, """
        select item_no, description, wh_code, est_on_hand, book_recorded_qty, est_minus_recorded, confidence, round(abs(est_minus_recorded) * std_cost, 0) as gap_value
        from marts.mart_stock_current where est_minus_recorded <> 0 order by abs(est_minus_recorded) * std_cost desc limit 25""")
    ms = con.execute("select count(*), avg((est_on_hand = book_recorded_qty)::int) from marts.mart_stock_current").fetchone()
    stock["agree_with_recorded"] = clean(ms[1])
    sizes["stock"] = write("stock.json", stock)

    # per-SKU index and daily histories
    cur = con.execute("""select item_no, description, category, wh_code, est_on_hand, available_to_promise, risk, confidence, daily_rate, days_of_cover, committed_units, book_recorded_qty,
                                last_anchor_date, transfer_from, transfer_qty, inbound_14d_qty from marts.mart_stock_current""").fetchdf()
    idx = {}
    for r in cur.itertuples(index=False):
        s = idx.setdefault(r.item_no, {"i": r.item_no, "d": r.description, "c": r.category, "w": [None] * len(wh_codes)})
        s["w"][wh_codes.index(r.wh_code)] = [clean(r.est_on_hand), clean(r.available_to_promise), RISK[r.risk], CONF[r.confidence], clean(round(r.daily_rate, 2)), clean(r.days_of_cover and round(r.days_of_cover, 1)),
                                             clean(r.committed_units), clean(r.book_recorded_qty), clean(r.last_anchor_date), clean(r.transfer_from), clean(r.transfer_qty), clean(r.inbound_14d_qty)]
    sizes["skus"] = write("skus.json", {"fields": ["est", "atp", "risk", "conf", "rate", "cover_days", "committed", "recorded", "last_count", "transfer_from", "transfer_qty", "inbound_14d"],
                                        "risk_codes": list(RISK), "conf_codes": list(CONF), "skus": sorted(idx.values(), key=lambda s: s["i"])})
    ndays = (as_of - d0).days + 1
    hist: dict[str, dict] = {}
    for wi, wh in enumerate(wh_codes):
        df = con.execute("""select item_no, cast(local_date - ? as integer) as day_off, est_on_hand, book_recorded_qty, confidence from marts.mart_stock_daily where wh_code = ? order by item_no, local_date""", [d0, wh]).fetchnumpy()
        items, off, est, rec, conf = df["item_no"], df["day_off"], df["est_on_hand"], df["book_recorded_qty"], df["confidence"]
        bounds = np.flatnonzero(np.r_[True, items[1:] != items[:-1], True])
        for a, b in zip(bounds[:-1], bounds[1:]):
            e = np.rint(est[a:b]).astype(np.int64)
            r = rec[a:b].astype(np.int64)
            cc = np.array([CONF[x] for x in conf[a:b]], dtype=np.int8)
            # run-length encode confidence: [code, length, code, length...]
            ch = np.flatnonzero(np.r_[True, cc[1:] != cc[:-1], True])
            rle = [int(v) for i in range(len(ch) - 1) for v in (cc[ch[i]], ch[i + 1] - ch[i])]
            h = hist.setdefault(items[a], {})
            h[wh] = {"s": int(off[a]), "e": [int(e[0])] + [int(x) for x in np.diff(e)], "r": [int(r[0])] + [int(x) for x in np.diff(r)], "c": rle}
    tot = 0
    for item, h in hist.items():
        tot += write(f"sku/{item}.json", {"start": d0.isoformat(), "days": ndays, "wh": h})
    sizes["sku_shards"] = tot

    # ----------------------------------------------------------------------------------------------------------------------------- risk
    risk = {"as_of": as_of.isoformat()}
    risk["summary"] = table(con, "select risk, count(*) as pairs, count(distinct item_no) as skus from marts.mart_stock_current group by 1 order by 1")
    risk["by_wh"] = table(con, "select wh_code, count(*) filter (where risk = 'at_risk') as at_risk, count(*) filter (where risk = 'out_of_stock') as out_of_stock, count(*) filter (where transfer_from is not null) as with_transfer from marts.mart_stock_current group by 1 order by 1")
    risk["rows"] = table(con, """
        select item_no, description, category, wh_code, risk, est_on_hand, confidence, round(daily_rate, 2) as daily_rate, round(days_of_cover, 1) as days_of_cover, inbound_14d_qty, first_inbound_in_days,
               transfer_from, transfer_qty, round(daily_rate * 14 * list_price, 0) as revenue_at_risk_14d
        from marts.mart_stock_current where risk in ('at_risk', 'out_of_stock')
        order by case risk when 'out_of_stock' then 0 else 1 end, daily_rate * list_price desc""")
    sizes["risk"] = write("risk.json", risk)

    # ----------------------------------------------------------------------------------------------------------------------------- inbound
    inb = {"as_of": as_of.isoformat()}
    inb["summary"] = table(con, "select count(*) as open_lines, sum(open_value) as open_value, count(*) filter (where days_overdue > 0) as overdue_lines, sum(open_value) filter (where days_overdue > 0) as overdue_value, avg(days_overdue) filter (where days_overdue > 0) as avg_days_overdue from marts.mart_inbound_open")[0]
    inb["by_wh"] = table(con, "select wh_code, count(*) as open_lines, sum(open_value) as open_value, count(*) filter (where days_overdue > 0) as overdue_lines from marts.mart_inbound_open group by 1 order by 1")
    inb["overdue"] = table(con, "select po_no, line_no, item_no, description, vendor_name, wh_code, promised_date, days_overdue, qty_ordered, round(open_value, 0) as open_value from marts.mart_inbound_open where days_overdue > 0 order by open_value desc limit 30")
    inb["due_next_14"] = table(con, f"select wh_code, count(*) as lines, sum(open_value) as total_value from marts.mart_inbound_open where promised_date between date '{as_of}' and date '{as_of}' + 14 group by 1 order by 1")
    inb["vendors"] = table(con, "select vendor_no, vendor_name, lines_received, on_time_rate, avg_days_vs_promise, value_received from marts.mart_vendor_ontime where lines_received >= 25 order by on_time_rate")
    sizes["inbound"] = write("inbound.json", inb)

    # ----------------------------------------------------------------------------------------------------------------------------- freight
    fr = {"as_of": as_of.isoformat()}
    weeks = [r["week"] for r in table(con, "select distinct week from marts.mart_freight_weekly where week > (select max(week) from marts.mart_freight_weekly) - interval 52 week order by 1")]
    fr["weeks"] = weeks
    series = {}
    for carrier in ("CARRIER_A", "CARRIER_B"):
        rows = {r["week"]: r for r in table(con, """
            select week, sum(shipments) as shipments, sum(cost) as cost, sum(duplicate_cost) as duplicate_cost, sum(cost) / nullif(sum(weight_lb) / 100.0, 0) as cost_per_100lb,
                   sum(cost) filter (where direction = 'outbound') / nullif(sum(order_shipments) filter (where direction = 'outbound'), 0) as cost_per_order,
                   sum(cost) filter (where direction = 'outbound') / nullif(sum(shipments) filter (where direction = 'outbound'), 0) as cost_per_outbound_shipment,
                   sum(slow_shipments) * 1.0 / nullif(sum(timed_shipments), 0) as slow_rate
            from marts.mart_freight_weekly where carrier = ? group by 1""", [carrier])}
        series[carrier] = {k: [rows.get(w, {}).get(k) for w in weeks] for k in ("shipments", "cost", "duplicate_cost", "cost_per_100lb", "cost_per_order", "slow_rate")}
    fr["series"] = series
    fr["by_carrier"] = table(con, """
        select carrier, count(*) as shipments, sum(cost) as cost, sum(duplicate_cost) as duplicate_cost, sum(cost) / nullif(sum(weight_lb) / 100.0, 0) as cost_per_100lb,
               sum(cost) filter (where doc_no like 'SO-%') / nullif(count(distinct doc_no) filter (where doc_no like 'SO-%'), 0) as cost_per_order,
               sum(cost) filter (where doc_no like 'SO-%') / nullif(sum(order_units) filter (where doc_no like 'SO-%'), 0) as cost_per_unit,
               count(*) filter (where is_slow) * 1.0 / nullif(count(*) filter (where transit_days is not null), 0) as slow_rate, median(transit_days) as median_transit_days
        from marts.mart_freight_shipment where pickup_date > date '@AS_OF@' - 368 and pickup_date <= date '@AS_OF@' - 3 group by 1 order by 1""".replace("@AS_OF@", str(as_of)))
    fr["lanes"] = table(con, """select carrier, lane, direction, shipments, cost, cost_per_100lb, median_transit_days, slow_shipments, timed_shipments from marts.mart_freight_lane order by cost desc limit 20""")
    fr["charges"] = table(con, """
        select s.carrier, c.charge_code, count(*) as lines, sum(c.amount) as amount from core.fct_freight_charge c join marts.mart_freight_shipment s using (shipment_key)
        where s.pickup_date > date '@AS_OF@' - 368 and s.pickup_date <= date '@AS_OF@' - 3 and not c.is_suspect_duplicate group by 1, 2 order by 1, 4 desc""".replace("@AS_OF@", str(as_of)))
    fr["duplicates"] = table(con, """select date_trunc('month', pickup_date) as month, carrier, sum(duplicate_cost) as recoverable, count(*) filter (where duplicate_cost > 0) as lines
                                     from marts.mart_freight_shipment where duplicate_cost > 0 group by 1, 2 order by 1, 2""")
    fr["standards"] = table(con, "select direction, max_transit_days, basis from ref.service_standards")
    sizes["freight"] = write("freight.json", fr)

    # ----------------------------------------------------------------------------------------------------------------------------- exceptions
    ex = {"as_of": as_of.isoformat()}
    ex["phantom_episodes"] = table(con, "select * from marts.mart_ghost_stock_episode order by alert_date")
    wk = table(con, """select wh_code, date_trunc('week', as_of) as week, round(avg(n_lines), 1) as avg_stuck_lines, max(threshold) as threshold, bool_or(is_alert) as alert
                        from marts.mart_ghost_stock_daily group by 1, 2 order by 1, 2""")
    ex["stuck_weekly"] = {"weeks": sorted({r["week"] for r in wk}), "series": {w: {} for w in wh_codes}, "threshold": {}}
    for r in wk:
        ex["stuck_weekly"]["series"][r["wh_code"]][r["week"]] = [r["avg_stuck_lines"], r["alert"]]
        ex["stuck_weekly"]["threshold"][r["wh_code"]] = r["threshold"]
    ex["phantom_skus"] = []
    if ex["phantom_episodes"]:
        e = ex["phantom_episodes"][0]
        ex["phantom_skus"] = table(con, """
            select l.item_no, s.description, count(*) as stuck_lines, sum(l.line_value) as stuck_value, min(l.order_date) as first_stuck_order, any_value(m.book_recorded_qty) as book_qty_on_alert, any_value(m.est_on_hand) as est_on_alert
            from marts.mart_ghost_stock_line l join core.dim_sku s using (item_no)
            join marts.mart_stock_daily m on m.item_no = l.item_no and m.wh_code = l.wh_code and m.local_date = cast(? as date)
            where l.wh_code = ? and l.order_date between cast(? as date) - 45 and cast(? as date) - 7 group by 1, 2 having count(*) >= 3 order by stuck_value desc limit 30""",
                                [e["alert_date"], e["wh_code"], e["alert_date"], e["last_alert_date"]])
    ex["count_accuracy"] = stock["count_accuracy"]
    ex["review_queue"] = table(con, """select reason_code, source_system, any_value(defect_class) as defect_class, any_value(severity) as severity, any_value(disposition) as disposition, any_value(owner_role) as owner,
                                       any_value(suggested_action) as suggested_action, count(*) as n from core.review_queue group by 1, 2 order by 8 desc""")
    ex["review_samples"] = {}
    for r in ex["review_queue"]:
        ex["review_samples"][r["reason_code"]] = table(con, "select source_key, detail from core.review_queue where reason_code = ? order by source_key limit 4", [r["reason_code"]])
    ex["handling_summary"] = table(con, """
        select 'Order lines dropped as duplicates' what, count(*) as n from core.fct_order_line where is_duplicate union all
        select 'Order lines excluded (bad quantity, warehouse or case size)', count(*) from core.fct_order_line where exclude_reason is not null and not is_duplicate union all
        select 'Legacy rows quarantined (bad quantity or ambiguous item)', count(*) from quarantine.q_legacy_trans union all
        select 'Count rows quarantined (bad SKU or date)', count(*) from quarantine.q_count_row union all
        select 'Shipments sent to review (reference unmatched)', count(*) from core.fct_shipment where match_status = 'REVIEW' union all
        select 'Duplicate carrier charge lines flagged', count(*) from core.fct_freight_charge where is_suspect_duplicate union all
        select 'Transfers recorded on one side only', count(*) from core.recon_transfer_exceptions union all
        select 'Receipts that disagree with the warehouse count', count(*) from core.recon_receipt_variance""")
    sizes["exceptions"] = write("exceptions.json", ex)

    # ----------------------------------------------------------------------------------------------------------------------------- pipeline health
    h = {"as_of": as_of.isoformat()}
    hd = con.execute("select as_of, health, open_errors, open_warnings from ops.pipeline_health_daily order by as_of").fetchall()
    h["nights"] = {"start": hd[0][0].isoformat(), "status": "".join({"green": "g", "amber": "a", "red": "r"}[x[1]] for x in hd)}
    h["today"] = table(con, "select * from ops.pipeline_health_current")[0]
    h["alerts"] = table(con, "select alert_id, alert_type, severity, entity, alert_code, opened_as_of, resolved_as_of, message from ops.alerts_unified order by opened_as_of desc, alert_id desc")
    h["freshness"] = table(con, """select f.stream, f.last_arrival, f.days_since_last_arrival, f.max_expected_gap_days, f.critical, f.is_late, m.owner, m.description
                                   from ops.freshness_daily f join ref.monitor_streams m using (stream) where f.as_of = (select max(as_of) from ops.freshness_daily) order by f.critical desc, f.stream""")
    h["layers"] = table(con, "select check_name, left_count, right_count, diff, ok from ops.layer_reconciliation")
    h["tests"] = table(con, """select count(*) as n, sum((status = 'pass')::int) as passed, max(generated_at) as tested_at from ops.dbt_test_result
                               where invocation_id = (select invocation_id from ops.dbt_invocation where command = 'test' order by generated_at desc limit 1) and unique_id like 'test.%'""")[0]
    keym = ["wms_duplicate_delivery_rate", "wms_late_arrival_rate", "erp_duplicate_line_rate", "freight_reference_unmatched_rate", "count_sku_unresolved_rate", "legacy_unparseable_quantity_rate"]
    h["metrics"] = {k: table(con, "select week, rate, p0, is_out_of_control ooc from ops.dq_metric_weekly where metric = ? and week > cast(? as date) - 400 and is_settled order by week", [k, as_of]) for k in keym}
    h["catalog"] = table(con, "select * from ops.dq_check_catalog")
    h["volume_today"] = table(con, "select count(*) as files from ops.ops_file_arrival where arrival = (select max(arrival) from ops.ops_file_arrival)")[0]
    sizes["health"] = write("health.json", h)

    # ----------------------------------------------------------------------------------------------------------------------------- manual effort (modeled)
    me = table(con, "select handling_key, label, minutes_per_item, basis, items, hours, is_remaining_manual from marts.mart_manual_effort order by hours desc")
    auto = sum(r["hours"] for r in me if not r["is_remaining_manual"])
    rem = sum(r["hours"] for r in me if r["is_remaining_manual"])
    sizes["manual_effort"] = write("manual_effort.json", {"modeled": True, "rows": me, "hours_automated": round(auto, 1), "hours_remaining": round(rem, 1),
                                                        "note": "MODELED estimate, not a measurement: counts come from the cleaned tables, minutes per item are assumptions shown beside each row."})

    # ----------------------------------------------------------------------------------------------------------------------------- overview
    k = con.execute("""select count(*), count(distinct item_no), sum(est_on_hand * std_cost) filter (where est_on_hand > 0), count(*) filter (where risk = 'at_risk'), count(*) filter (where risk = 'out_of_stock'),
                              avg((confidence = 'suspect')::int), sum(available_to_promise) filter (where available_to_promise > 0) from marts.mart_stock_current""").fetchone()
    fr30 = con.execute(f"select sum(cost), count(*) filter (where is_slow) * 1.0 / nullif(count(*) filter (where transit_days is not null), 0), count(*) from marts.mart_freight_shipment where pickup_date > date '{as_of}' - 33 and pickup_date <= date '{as_of}' - 3").fetchone()
    last30 = h["nights"]["status"][-30:]
    ep = ex["phantom_episodes"][0] if ex["phantom_episodes"] else None
    ov = {"as_of": as_of.isoformat(), "pairs": k[0], "skus": k[1], "est_value": clean(k[2]), "at_risk": k[3], "out_of_stock": k[4], "suspect_share": clean(k[5]), "atp_units": clean(k[6]),
          "inbound": inb["summary"], "freight_30d": {"cost": clean(fr30[0]), "slow_rate": clean(fr30[1]), "shipments": fr30[2]},
          "health_30d": {"green": last30.count("g"), "amber": last30.count("a"), "red": last30.count("r")}, "health_today": h["today"], "tests": h["tests"],
          "layers_ok": sum(1 for r in h["layers"] if r["ok"]), "layers": len(h["layers"]), "streams_late": sum(1 for r in h["freshness"] if r["is_late"]), "streams": len(h["freshness"]),
          "review_rows": sum(r["n"] for r in ex["review_queue"]), "manual": {"automated": round(auto, 1), "remaining": round(rem, 1)}, "phantom": ep,
          "exact_vs_recorded": stock["agree_with_recorded"], "warehouses": whs, "history_start": d0.isoformat(), "history_days": ndays,
          "recoverable_freight": clean(con.execute("select sum(duplicate_cost) from marts.mart_freight_shipment").fetchone()[0])}
    sizes["overview"] = write("overview.json", ov)
    write("meta.json", {"as_of": as_of.isoformat(), "history_start": d0.isoformat(), "days": ndays, "warehouses": whs, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "synthetic": True, "sizes": sizes})
    con.close()
    total = sum(p.stat().st_size for p in OUT.rglob("*.json"))
    print(f"exported {len(list(OUT.rglob('*.json'))):,} files, {total / 1e6:.1f} MB (shards {sizes['sku_shards'] / 1e6:.1f} MB) to {OUT}")
    return sizes


if __name__ == "__main__":
    main()
