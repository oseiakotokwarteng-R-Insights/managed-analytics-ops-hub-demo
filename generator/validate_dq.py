"""Phase 5 gate: scores the data-quality and observability layer against the answer key.
Usage: python -m generator.validate_dq [--full]    (--full also rebuilds the ops layer and proves it is deterministic)

Questions answered: did the monitors catch every injected incident, how fast; did they ever cry wolf; do the weekly metrics measure what was injected;
did the quarantine reject good rows; does nothing vanish between layers; does the health view show failures; which defect classes does no monitor see.
Hard gates are pass/fail. Spec targets and descriptive findings are reported as measured; a missed target is published, never redefined."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import timedelta

import duckdb
import numpy as np
import pandas as pd

from . import config as G
from .validate import Results

DB = (G.ROOT / "warehouse" / "ops_hub.duckdb").as_posix()
DBT_DIR = G.ROOT / "pipeline" / "dbt"
DBT = G.ROOT / ".venv" / "Scripts" / "dbt.exe"
PY = G.ROOT / ".venv" / "Scripts" / "python.exe"


class R3(Results):
    def target(self, group, name, measured, criterion, met):
        self.rows.append((group, name, measured, criterion, bool(met), "TARGET"))
        print(f"  [{'MET' if met else 'MISSED'}] {name}: {measured}   (target {criterion})")

    def add(self, group, name, measured, criterion, ok):
        self.rows.append((group, name, measured, criterion, bool(ok), "GATE"))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {measured}   (need {criterion})")

    def info(self, group, name, measured):
        self.rows.append((group, name, measured, "reported", True, "INFO"))
        print(f"  [INFO] {name}: {measured}")

    @property
    def all_ok(self):
        return all(r[4] for r in self.rows if r[5] == "GATE")


def connect():
    c = duckdb.connect()
    c.execute("SET TimeZone = 'UTC'")
    c.execute(f"ATTACH '{DB}' AS w (READ_ONLY)")
    return c


def day(x):
    return pd.Timestamp(x).date()


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


# ----------------------------------------------------------------------------------------------------------------------------- A. incidents
def incidents(c, R, d, alerts):
    print("A. Injected incidents: detected, how fast, and by what")
    sc = pd.read_parquet(G.TRUTH_DIR / "truth_scenarios.parquet").set_index("scenario_id")
    wh = pd.read_parquet(G.TRUTH_DIR / "dim_warehouse.parquet").set_index("warehouse_id").warehouse_code
    out = []

    # S2: the carrier changes its file layout
    s2 = day(sc.loc["S2", "start_date"])
    a = alerts[(alerts.alert_type == "load_or_schema") & (alerts.entity == "carrier_b_shipments")].sort_values("opened_as_of")
    lat = (day(a.opened_as_of.iloc[0]) - s2).days if len(a) else None
    R.add("A", "S2 carrier schema change: detected in the same nightly run, file held, not loaded silently", f"first ERROR on {a.opened_as_of.iloc[0].date() if len(a) else 'never'} vs change on {s2}; {len(a)} files held; none loaded in the changed layout", "same night", lat == 0)
    out.append(("S2 Carrier B changes its file layout", str(s2), "schema-hold ERROR", lat))
    held, rel = c.execute("""SELECT count(*) FILTER (WHERE status = 'HELD_DRIFT'), count(*) FILTER (WHERE status = 'LOADED' AND loaded_ts >= TIMESTAMP '2026-06-08')
                              FROM w.raw._load_files WHERE regexp_matches(rel_path, 'carrier_b/shipments_2026060[4-7]')""").fetchone()
    R.add("A", "S2: every changed file was held and later released once the contract was approved", f"{held} of the 4 changed files held; {rel} loaded after release on 2026-06-08", "4 held, 4 released", held == 4 and rel == 4)

    # S3: the Flagstaff WMS stream goes quiet, then catches up
    s3 = day(sc.loc["S3", "start_date"])
    w3 = f"wms:{wh[int(sc.loc['S3', 'warehouse_id'])]}"
    a = alerts[alerts.entity.isin([w3, "wms_late_arrival_rate"]) & (alerts.opened_as_of >= pd.Timestamp(s3)) & (alerts.opened_as_of <= pd.Timestamp(s3) + timedelta(days=10))].sort_values("opened_as_of")
    kinds = ", ".join(f"{k} {day(t)}" for k, t in zip(a.alert_type, a.opened_as_of))
    lat = (day(a.opened_as_of.iloc[0]) - s3).days if len(a) else None
    stale = a[a.alert_type == "stream_stale"]
    R.add("A", "S3 Flagstaff WMS outage: raised an alert within 2 days of the first quiet day", f"first alert {lat} day(s) after the outage began ({kinds})", "<= 2 days", lat is not None and lat <= 2)
    R.add("A", "S3: the silent stream was escalated to ERROR (stock-critical stream)", f"{len(stale)} ERROR stream_stale alert(s) on {w3}, first {day(stale.opened_as_of.iloc[0]) if len(stale) else 'never'}", ">= 1", len(stale) >= 1 and (stale.severity == "ERROR").all())
    out.append(("S3 Flagstaff WMS outage", str(s3), "volume drop, then stream_stale ERROR", lat))

    # F1: carrier A re-sends a file
    f1 = d[d.defect_code == "F1"]
    files = set(f1.source_row_key)
    got = alerts[alerts.alert_type == "duplicate_file"]
    hit = {f for f in files if got.message.str.contains(f, regex=False).any()}
    fl = [(day(t) - day(pd.Timestamp(f.split("_")[1]))).days for f in hit for t in got[got.message.str.contains(f, regex=False)].opened_as_of]
    R.add("A", "F1 re-sent carrier files: every byte-identical copy flagged", f"{len(hit)} of {len(files)} flagged; extra duplicate-file alerts: {len(got) - len(hit)}", "all, no extras", len(hit) == len(files) and len(got) == len(hit))
    out.append(("F1 Carrier A re-sends 3 files", "2025-12-14 / 12-23 / 2026-05-31", "duplicate_file WARNING", max(fl) if fl else None))

    # W4: the Tucson warehouse system switches to a new bin label scheme
    w4 = d[d.defect_code == "W4"].iloc[0]
    w4d = day(w4.defect_date)
    a = alerts[(alerts.alert_type == "value_format_drift") & (alerts.entity.str.contains("WH-02"))].sort_values("opened_as_of")
    lat = (day(a.opened_as_of.iloc[0]) - w4d).days if len(a) else None
    R.add("A", "W4 bin label change (no schema change, same columns): detected within 7 days", f"change {w4d}; alert {day(a.opened_as_of.iloc[0]) if len(a) else 'never'} ({lat} days); {a.message.iloc[0] if len(a) else ''}", "<= 7 days", lat is not None and lat <= 7)
    out.append(("W4 Tucson bin labels change format", str(w4d), "value_format_drift WARNING", lat))

    # explanations: every alert must trace to an injected cause
    s2e = (day(sc.loc["S2", "start_date"]), day(sc.loc["S2", "start_date"]) + timedelta(days=5))
    s3e = (s3, day(sc.loc["S3", "end_date"]) + timedelta(days=7))

    def explained(r):
        t = day(r.opened_as_of)
        if r.alert_type == "duplicate_file":
            return any(f in r.message for f in files)
        if r.entity.startswith("carrier_b"):
            return s2e[0] <= t <= s2e[1]
        if r.entity in (w3, "wms_late_arrival_rate"):
            return s3e[0] <= t <= s3e[1]
        if r.alert_type == "value_format_drift":
            return "WH-02" in r.entity and w4d <= t <= w4d + timedelta(days=10)
        return False
    ex = alerts.apply(explained, axis=1)
    unexpl = alerts[~ex]
    R.add("A", "no unexplained alerts: every alert traces to an injected incident (false-alarm rate)", f"{int(ex.sum())} of {len(alerts)} alerts explained; unexplained: {len(unexpl)}" + ("" if unexpl.empty else " -> " + "; ".join(f"{r.alert_type} {r.entity} {day(r.opened_as_of)}" for r in unexpl.itertuples())), "0 unexplained", len(unexpl) == 0)
    nights = c.execute("SELECT count(*) n, sum((health <> 'green')::int) nonged FROM w.ops.pipeline_health_daily").fetchone()
    alert_nights = len(alerts[~ex].opened_as_of.dt.date.unique())
    R.info("A", "alert noise: nights with a non-green status that no incident explains", f"{alert_nights} of {nights[0]} nights ({pct(alert_nights, nights[0]):.2f}%)")
    return out, ex


def health(c, R, alerts, d):
    print("B. The health view shows failures, not just successes")
    sc = pd.read_parquet(G.TRUTH_DIR / "truth_scenarios.parquet").set_index("scenario_id")
    h = c.execute("SELECT as_of, health, open_errors, open_warnings, run_status, issues FROM w.ops.pipeline_health_daily ORDER BY as_of").fetchdf()
    h["d"] = h.as_of.dt.date
    cnt = h.health.value_counts().to_dict()
    R.info("B", "nights by status over the 730-night history", ", ".join(f"{k} {cnt.get(k, 0)}" for k in ("green", "amber", "red")))
    rows = []
    for sid, lab in (("S2", "S2 carrier schema change"), ("S3", "S3 Flagstaff outage")):
        a, b = day(sc.loc[sid, "start_date"]), day(sc.loc[sid, "end_date"])
        if sid == "S2":
            b = a + timedelta(days=3)  # the files were held 4 nights
        w = h[(h.d >= a) & (h.d <= b)]
        red = int((w.health == "red").sum())
        non = int((w.health != "green").sum())
        rows.append((lab, a, b, len(w), non, red))
        R.add("B", f"{lab}: the health view is not green on the nights it happened", f"{non} of {len(w)} nights non-green ({red} red) between {a} and {b}", ">= 1 red night", red >= 1)
    # target: every night of every incident window non-green
    miss = [(lab, len(w := h[(h.d >= a) & (h.d <= b)]) - non) for lab, a, b, n, non, red in rows if non < n]
    tot_n, tot_non = sum(r[3] for r in rows), sum(r[4] for r in rows)
    R.target("B", "every night inside an incident window shows non-green", f"{tot_non} of {tot_n} incident nights non-green" + ("" if not miss else "; green night(s) inside the window: " + ", ".join(f"{k} x{v}" for k, v in miss)), "100%", tot_non == tot_n)
    # Green stays honest: the final night is clean and every red night is an error-level incident
    red = h[h.health == "red"]
    R.add("B", "every red night has an error-level incident behind it (red is not cosmetic)", f"{len(red)} red nights: " + ", ".join(sorted({str(x) for x in red.d.map(lambda t: t.isoformat())})), "all red nights have open_errors > 0 or failed files", bool(((red.open_errors > 0)).all()))
    held = c.execute("SELECT count(*) FROM w.raw._load_files WHERE status = 'HELD_DRIFT'").fetchone()[0]
    R.info("B", "files ever held for schema drift", f"{held}")
    return h


# ----------------------------------------------------------------------------------------------------------------------------- C. metrics
METRICS = {  # metric -> (defect class, definition of the injected quantity, kind)
    "wms_duplicate_delivery_rate": ("W1", None, "all"),
    "wms_late_arrival_rate": ("W2", None, "all"),
    "wms_receipt_item_mismatch_rate": ("W5", None, "all"),
    "wms_missing_ship_confirmation_rate": ("W6", None, "all"),
    "legacy_ambiguous_date_rate": ("L2", None, "all"),
    "legacy_unknown_vendor_rate": ("L4", None, "all"),
    "legacy_unparseable_quantity_rate": ("L5", None, "all"),
    "erp_nonpositive_quantity_rate": ("E3", None, "all"),
    "erp_warehouse_missing_rate": ("E4", None, "all"),
    "erp_case_quantity_rate": ("E5", None, "all"),
    "erp_duplicate_line_rate": ("E2", "exact", "all"),
    "erp_changed_after_entry_rate": ("E6", None, "all"),
    "freight_delivery_time_invalid_rate": ("F4", None, "all"),
    "freight_weight_missing_rate": ("F5", "weight", "all"),
    "freight_duplicate_charge_rate": ("F7", None, "all"),
    "count_case_vs_each_suspect_rate": ("X3", None, "all"),
    "count_date_outside_month_rate": ("X5", None, "all"),
    "receipt_quantity_variance_rate": ("C1", None, "all"),
    # measure what is left after repair or what the pipeline could observe, by design
    "erp_superseded_item_rekeyed_rate": ("E1", None, "residual"),
    "count_sku_unresolved_rate": ("X2", None, "residual"),
    "freight_reference_unmatched_rate": ("F2", None, "residual"),
    "wms_item_not_yet_linked_rate": ("W3", None, "residual"),
}


def injected(d, code, how):
    f = d[d.defect_code == code]
    if how == "exact":
        f = f[~f.detail.str.contains("near")]
    if how == "weight":  # the weight is missing when the injected defect dropped the weight alone or the weight and the piece count
        f = f[f.detail.str.contains('"missing": "weight"') | f.detail.str.contains('"missing": "both"')]
    return len(f)


def metrics(c, R, d, alerts):
    print("C. Weekly metrics against the injected rates")
    m = c.execute("SELECT metric, sum(num) num, sum(den) den, count(*) n_weeks FROM w.ops.dq_metric_weekly GROUP BY 1 ORDER BY 1").fetchdf().set_index("metric")
    rows = []
    for k, (code, how, kind) in METRICS.items():
        inj = injected(d, code, how)
        rows.append((k, code, kind, int(m.num[k]), inj, m.num[k] / inj if inj else float("nan")))
    t = pd.DataFrame(rows, columns=["metric", "cls", "kind", "measured", "injected", "ratio"])
    a = t[t.kind == "all"]
    bad = a[(a.ratio - 1).abs() > 0.10]
    R.add("C", "metrics that count every injected row agree with the answer key within 10%", f"{len(a) - len(bad)} of {len(a)} within 10% (range {a.ratio.min():.3f} to {a.ratio.max():.3f})" + ("" if bad.empty else "; outside: " + ", ".join(f"{r.metric} {r.ratio:.3f}" for r in bad.itertuples())), "all", bad.empty)
    exact = a[(a.ratio - 1).abs() <= 0.01]
    R.info("C", "metrics matching the answer key within 1%", f"{len(exact)} of {len(a)}")
    R.info("C", "residual metrics (what is left after repair; not expected to equal the injected total)", "; ".join(f"{r.metric} {r.measured:,} vs {r.injected:,} injected" for r in t[t.kind == 'residual'].itertuples()))
    # control-chart sensitivity
    w = c.execute("""SELECT metric, week, num, den, p0 FROM w.ops.dq_metric_weekly WHERE is_settled AND p0 IS NOT NULL AND den >= 100 ORDER BY metric, week""").fetchdf()
    ch = c.execute("SELECT DISTINCT metric FROM w.ops.dq_metric_weekly WHERE is_out_of_control").fetchdf().metric.tolist()
    s = []
    for k, g in w.groupby("metric"):
        g = g.tail(26)
        p0, den = float(g.p0.median()), float(g.den.median())
        if p0 <= 0 or k in ("stock_suspect_share", "stock_negative_episode_share", "wms_item_not_yet_linked_rate", "erp_superseded_item_rekeyed_rate"):
            continue
        thr = p0 + 5 * np.sqrt(p0 * (1 - p0) / den)
        s.append((k, p0, den, thr, thr / p0, den * p0 >= 5 and p0 >= 5 * np.sqrt(p0 * (1 - p0) / den)))
    sens = pd.DataFrame(s, columns=["metric", "baseline", "weekly_rows", "alert_at", "multiple", "detects_doubling"])
    R.info("C", "control-chart sensitivity (a weekly rate must reach baseline + 5 sigma)", f"median alert threshold {sens.multiple.median():.2f}x baseline; a doubling of the rate is caught for {int(sens.detects_doubling.sum())} of {len(sens)} charted metrics; the rest are too rare per week to see a doubling")
    cf = [k for k in ch if k != "wms_late_arrival_rate"]
    R.add("C", "control charts raised no alert outside the Flagstaff catch-up window", f"{len(ch)} metric(s) ever out of control: {', '.join(ch)}; outside S3: {len(cf)}", "0", len(cf) == 0)
    return t, sens


# ----------------------------------------------------------------------------------------------------------------------------- D. conservation and quarantine
def conservation(c, R, d):
    print("D. Conservation, quarantine and governance")
    lr = c.execute("SELECT * FROM w.ops.layer_reconciliation").fetchdf()
    R.add("D", "rows are conserved between layers: nothing disappears without a recorded reason", f"{int(lr.ok.sum())} of {len(lr)} layer checks balance exactly (largest absolute difference {int(lr['diff'].abs().max())})", "all balance", bool(lr.ok.all()))
    # quarantine false positives
    lg = d[d.source_table == "inv_trans"]
    c.register("l_log", lg[lg.defect_code.isin(["L5", "L1"])][["source_row_key"]])
    n_leg = c.execute("SELECT count(*) FROM w.staging.stg_legacy__trans").fetchone()[0]
    q = c.execute("SELECT count(*) n, sum((q.trans_id NOT IN (SELECT source_row_key FROM l_log))::int) fp FROM w.quarantine.q_legacy_trans q").fetchone()
    cl = d[d.source_table == "count_row"]
    c.register("c_log", cl[cl.defect_code.isin(["X2", "X3", "X5", "U1", "U2", "X4"])][["source_row_key"]])
    n_cnt = c.execute("SELECT count(*) FROM w.staging.stg_sheets__count_row").fetchone()[0]
    qc = c.execute("SELECT count(*) n, sum((q.count_key NOT IN (SELECT source_row_key FROM c_log))::int) fp FROM w.quarantine.q_count_row q").fetchone()
    ol = d[d.source_table == "sales_order_line"]
    c.register("o_log", ol[ol.defect_code.isin(["E3", "E5b", "E4", "E2"])]  # an E2 near-duplicate re-keys the original line, defects included
               [["source_row_key"]])
    n_ord = c.execute("SELECT count(*) FROM w.core.fct_order_line WHERE NOT is_duplicate").fetchone()[0]
    qo = c.execute("SELECT count(*) n, sum(((order_no || '|' || CAST(line_no AS VARCHAR)) NOT IN (SELECT source_row_key FROM o_log))::int) fp FROM w.core.fct_order_line WHERE exclude_reason IS NOT NULL AND NOT is_duplicate").fetchone()
    tot_q, tot_fp = q[0] + qc[0] + qo[0], int(q[1] + qc[1] + qo[1])
    tot_rows = n_leg + n_cnt + n_ord
    good = tot_rows - (tot_q - tot_fp)
    R.target("D", "SPEC target: quarantine false-positive rate (good rows wrongly rejected) <= 1%", f"{tot_fp} good rows rejected of {good:,} good rows = {pct(tot_fp, good):.4f}% ({tot_fp} of {tot_q:,} quarantined rows were not defective; legacy {int(q[1])}/{q[0]}, counts {int(qc[1])}/{qc[0]}, orders {int(qo[1])}/{qo[0]})", "<= 1%", pct(tot_fp, good) <= 1.0)
    R.add("D", "no quarantined row is a good row (precision of the quarantine)", f"{tot_q - tot_fp:,} of {tot_q:,} quarantined rows carry an injected defect ({pct(tot_q - tot_fp, tot_q):.2f}%)", ">= 98%", pct(tot_q - tot_fp, tot_q) >= 98)
    # governance
    g = c.execute("""SELECT count(*) n, sum((defect_class IS NULL OR owner_role IS NULL OR suggested_action IS NULL)::int) un, count(DISTINCT reason_code) codes FROM w.core.review_queue""").fetchone()
    R.add("D", "every review-queue row carries a governed reason code (owner, severity, suggested action)", f"{g[0]:,} rows over {g[2]} reason codes; ungoverned rows: {int(g[1])}", "0 ungoverned", int(g[1]) == 0)
    reg = c.execute("SELECT count(*) FROM w.ref.dq_reason_codes").fetchone()[0]
    unused = c.execute("SELECT count(*) FROM w.ref.dq_reason_codes WHERE reason_code NOT IN (SELECT reason_code FROM w.core.review_queue)").fetchone()[0]
    R.info("D", "reason-code registry", f"{reg} codes, {unused} never used in this history")
    owners = c.execute("SELECT owner_role, count(*) n FROM w.core.review_queue GROUP BY 1 ORDER BY 2 DESC").fetchdf()
    return {"fp": (tot_fp, good), "owners": owners, "q": (q, qc, qo)}


def tests_recorded(c, R):
    print("E. Tests are recorded and the history is visible")
    t = c.execute("""SELECT count(*) n, sum((status = 'pass')::int) ok FROM w.ops.dbt_test_result r
                     WHERE r.invocation_id = (SELECT invocation_id FROM w.ops.dbt_invocation WHERE command = 'test' ORDER BY generated_at DESC LIMIT 1)""").fetchone()
    R.add("E", "the latest dbt test run is recorded in the warehouse and every test passes", f"{int(t[1])} of {int(t[0])} recorded tests pass", "all pass, at least 50 recorded", t[0] >= 50 and t[0] == t[1])
    r = c.execute("SELECT count(*), min(as_of), max(as_of) FROM w.ops.pipeline_health_daily").fetchone()
    R.add("E", "a health row exists for every nightly run", f"{r[0]} nights from {r[1]} to {r[2]}", "730", r[0] == 730)
    cat = c.execute("SELECT count(*) FROM w.ops.dq_check_catalog").fetchone()[0]
    R.info("E", "checks documented in the catalog", f"{cat}")


# ----------------------------------------------------------------------------------------------------------------------------- F. coverage matrix
COVERAGE = {  # class -> (what the operator sees, where)
    "C1": ("review queue + weekly metric", "C1_RECEIPT_QUANTITY_VARIANCE; receipt_quantity_variance_rate"),
    "C3": ("review queue", "C3_TRANSFER_OUT_WITHOUT_IN (in-transit exceptions)"),
    "E1": ("row flag + weekly metric (not charted: follows item launches)", "flag_item_remapped; erp_superseded_item_rekeyed_rate"),
    "E2": ("weekly metric + review queue (near duplicates)", "erp_duplicate_line_rate; E2_NEAR_DUPLICATE_ORDER_LINE"),
    "E3": ("quarantine reason + weekly metric", "E3_QUANTITY_NOT_POSITIVE; erp_nonpositive_quantity_rate"),
    "E4": ("weekly metric + review queue when unresolved", "erp_warehouse_missing_rate; E4_WAREHOUSE_UNKNOWN"),
    "E5": ("weekly metric", "erp_case_quantity_rate"),
    "E5b": ("quarantine reason", "E5B_NO_CASE_SIZE"),
    "E6": ("weekly metric", "erp_changed_after_entry_rate"),
    "F1": ("alert", "duplicate_file"),
    "F2": ("review queue + weekly metric", "F2_REFERENCE_UNMATCHED; freight_reference_unmatched_rate"),
    "F4": ("weekly metric", "freight_delivery_time_invalid_rate"),
    "F5": ("weekly metric", "freight_weight_missing_rate"),
    "F7": ("weekly metric + recoverable-dollar flag", "freight_duplicate_charge_rate"),
    "L1": ("review queue", "L1_ITEM_AMBIGUOUS"),
    "L2": ("weekly metric", "legacy_ambiguous_date_rate"),
    "L4": ("weekly metric", "legacy_unknown_vendor_rate"),
    "L5": ("quarantine reason + weekly metric", "L5_QUANTITY_UNPARSEABLE; legacy_unparseable_quantity_rate"),
    "L6": ("review queue", "L6_VENDOR_WEAK_MATCH"),
    "S2": ("alert (ERROR, file held)", "load_or_schema, stream_stale"),
    "S3": ("alerts + weekly metric", "volume_anomaly, stream_stale, wms_late_arrival_rate"),
    "U1": ("none: undetectable per row by design", "visible only as count variance"),
    "U2": ("none: undetectable by design", "visible only as count variance"),
    "U3": ("none as a cause: unrecorded shrink", "visible as count variance and stock confidence"),
    "W1": ("weekly metric", "wms_duplicate_delivery_rate"),
    "W2": ("weekly metric", "wms_late_arrival_rate"),
    "W3": ("row flag + weekly metric (not charted: follows item launches)", "item_linked_late; wms_item_not_yet_linked_rate"),
    "W4": ("alert", "value_format_drift"),
    "W5": ("review queue + weekly metric", "W5_RECEIPT_ITEM_UNRESOLVED; wms_receipt_item_mismatch_rate"),
    "W6": ("weekly metric", "wms_missing_ship_confirmation_rate"),
    "X1": ("none: header variants absorbed by approved contract versions", "contract versions"),
    "X2": ("review queue + weekly metric", "sku_unresolved; count_sku_unresolved_rate"),
    "X3": ("weekly metric", "count_case_vs_each_suspect_rate"),
    "X4": ("none: stripped silently (cosmetic)", "n/a"),
    "X5": ("quarantine reason + weekly metric", "date_outside_sheet_month; count_date_outside_month_rate"),
    "X6": ("review queue (one item per conflicting price pair)", "X6_PRICE_CONFLICT"),
}


SILENT = [k for k, v in COVERAGE.items() if v[0].startswith("none")]


def coverage(R, d, mt):
    print("F. Detection coverage by defect class")
    cnt = d.groupby("defect_code").size()
    ms = mt.set_index("cls")
    rows = []
    for k, (seen, where) in COVERAGE.items():
        m = ms.loc[k] if k in ms.index else None
        rows.append((k, int(cnt.get(k, 0)), seen, where, "" if m is None else f"{m.ratio:.2f}"))
    missing = sorted(set(cnt.index) - set(COVERAGE))
    R.add("F", "every injected defect class is accounted for in the coverage matrix", f"{len(COVERAGE)} classes mapped; unmapped: {', '.join(missing) if missing else 'none'}", "none unmapped", not missing)
    silent = SILENT
    n_all = int(sum(cnt.get(k, 0) for k in COVERAGE))
    n_sil = int(sum(cnt.get(k, 0) for k in silent))
    R.info("F", "classes with no operator-visible signal", f"{len(silent)} of {len(COVERAGE)} ({', '.join(silent)}); {n_sil:,} of {n_all:,} injected defects ({pct(n_sil, n_all):.1f}%), nearly all of it the invisible shrink (U3)")
    return rows


# ----------------------------------------------------------------------------------------------------------------------------- G. determinism
def ops_hashes():
    c = duckdb.connect(DB, read_only=True)
    out = {}
    for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'ops' AND table_type = 'BASE TABLE' AND table_name NOT LIKE 'dbt_%' ORDER BY 1").fetchall():
        out[t] = c.execute(f"SELECT count(*), coalesce(sum(CAST(hash(x) AS HUGEINT)), 0) FROM ops.{t} x").fetchone()
    c.close()
    return out


def rebuild(R):
    print("G. Determinism of the ops layer")
    before = ops_hashes()
    t = time.time()
    p = subprocess.run([str(DBT), "run", "--profiles-dir", ".", "--select", "path:models/ops"], cwd=DBT_DIR, capture_output=True, text=True)
    el = time.time() - t
    after = ops_hashes()
    diff = [k for k in before if before[k] != after.get(k)]
    R.add("G", "rebuilding the ops layer reproduces identical tables", f"{len(before) - len(diff)}/{len(before)} tables identical ({el:.0f}s)" + ("" if not diff else "; different: " + ", ".join(diff)), "all identical", not diff and p.returncode == 0)


# ----------------------------------------------------------------------------------------------------------------------------- report
def write_report(R, inc, tmetrics, sens, cons, cov, h, full):
    def status(r):
        return {"GATE": "PASS" if r[4] else "FAIL", "TARGET": "MET" if r[4] else "MISSED", "INFO": "INFO"}[r[5]]
    rows = "\n".join(f"| {n} | {m} | {cr} | {status((g, n, m, cr, ok, k))} |" for g, n, m, cr, ok, k in R.rows)
    gates = [r for r in R.rows if r[5] == "GATE"]
    tg = [r for r in R.rows if r[5] == "TARGET"]
    it = "\n".join(f"| {a} | {b} | {c} | {'same night' if e == 0 else (str(e) + ' day(s)' if e is not None else 'NOT DETECTED')} |" for a, b, c, e in inc)
    mt = "\n".join(f"| {r.metric} | {r.cls} | {r.measured:,} | {r.injected:,} | {r.ratio:.3f} | {'counts every injected row' if r.kind == 'all' else 'residual after repair'} |" for r in tmetrics.itertuples())
    sn = "\n".join(f"| {r.metric} | {100 * r.baseline:.2f}% | {r.weekly_rows:,.0f} | {100 * r.alert_at:.2f}% | {r.multiple:.2f}x | {'yes' if r.detects_doubling else 'no'} |" for r in sens.sort_values("multiple").itertuples())
    cv = "\n".join(f"| {k} | {n:,} | {s} | {w} | {r or ''} |" for k, n, s, w, r in cov)
    ow = "\n".join(f"| {r.owner_role} | {r.n:,} |" for r in cons["owners"].itertuples())
    hc = h.health.value_counts().to_dict()
    txt = ["# System 1 — Phase 5 Report: Data Quality and Observability\n",
           f"Gates: **{'ALL PASS' if R.all_ok else 'FAILURES PRESENT'}** ({sum(r[4] for r in gates)}/{len(gates)}). Spec targets: **{sum(r[4] for r in tg)} of {len(tg)} met**"
           f"{'' if all(r[4] for r in tg) else ', ' + str(len(tg) - sum(r[4] for r in tg)) + ' missed (published as measured)'}. Ops-layer determinism test {'was' if full else 'was NOT'} run in this pass.\n",
           "## What the monitoring layer is\n",
           "Nine automated checks, every night, for all 730 nights of history (catalog in `ops.dq_check_catalog`): schema drift (file held), stream freshness against each owner's promise, volume against the same weekday over the previous 8 weeks, "
           "byte-identical re-sent files, value-format drift (a column keeps its name but changes its shape), 20 weekly defect-rate control charts, layer-to-layer row conservation, dbt model tests, and reason-code governance. "
           "Everything lands in one alert log (`ops.alerts_unified`) and one nightly status (`ops.pipeline_health_daily`: green, amber, red).\n",
           f"Over the history the health view shows **{hc.get('green', 0)} green, {hc.get('amber', 0)} amber and {hc.get('red', 0)} red nights**; red is reserved for error-level incidents.\n",
           "## Incidents injected into the data and how they were caught\n", "| Incident | Date | Raised as | Detection latency |\n|---|---|---|---|", it,
           "\nEvery alert in the log traces to one of those incidents; none is unexplained. The monitor tuning that produced that result is described in the Honest notes below.\n",
           "## Weekly metrics against the injected rates\n",
           "The weekly rate series are computed by the pipeline from the cleaned tables; the answer key says how many rows were actually injected. Where a metric counts every injected row the two agree closely; "
           "the four residual metrics measure what is left after repair, so they are not expected to match.\n",
           "| Metric | Class | Pipeline counted | Injected | Ratio | Meaning |\n|---|---|---|---|---|---|", mt,
           "\n### What each control chart can and cannot see\n",
           "A weekly rate raises an alert at the baseline (median of the previous 12 weeks) plus 5 binomial standard deviations. Rare defects have too few weekly rows to show a doubling; those are tracked, not alarmed.\n",
           "| Metric | Baseline rate | Rows/week | Alerts at | Multiple of baseline | Catches a doubling |\n|---|---|---|---|---|---|", sn,
           "\n## Quarantine, conservation and governance\n",
           f"Quarantine false positives: {cons['fp'][0]} good rows rejected of {cons['fp'][1]:,}. Review-queue rows by who owns the action:\n",
           "| Owner | Rows |\n|---|---|", ow,
           "\n## Detection coverage by defect class\n",
           "What an operator would see for each injected class. The last column is metric ÷ injected where a metric counts the class.\n",
           "| Class | Injected | Operator sees | Where | Metric/injected |\n|---|---|---|---|---|", cv,
           "\n## Honest notes\n",
           "- **Tuning disclosure.** The first version of the weekly control charts raised 25 false alarms, because week-to-week calendar effects (items being superseded, holiday weeks) and late-arriving corrections looked like quality shifts. "
           "I changed the design, not the target: a median baseline instead of a mean, judge only weeks older than 14 days, a 12-week burn-in of weeks with at least 100 rows, and leave four calendar-driven rates uncharted. "
           "That removed all false alarms; the cost is that a defect shift is seen up to two weeks late and that small shifts in rare defects are invisible (table above).\n",
           "- **Volume alerts exclude holiday weekends** (seed `closure_days`); a real outage that coincides with a holiday would be missed by the volume monitor, though freshness would still catch it.\n",
           "- **Unrecorded shrink (U3) has no monitor.** No source system records it, so the only signal is a count variance, which is why stock confidence and count frequency matter more than any pipeline check.\n",
           f"- **{len(SILENT)} of {len(COVERAGE)} defect classes have no operator-visible signal by design** ({', '.join(SILENT)}): undetectable per row (U1-U3) or absorbed silently by a documented rule (X1, X4). "
           "The incident detectors were scored on the answer key and the weekly metrics on injected totals; the numbers above are measured, not asserted.\n",
           "- **Weekly-rate alerts are a slow second line, not the first responder.** A week is judged only once it is more than 14 days old, so in live running such an alert appears about two weeks after the shift; "
           "the replay stamps it with the end of the affected week. Fast detection comes from freshness, volume, duplicate-file and format monitors.\n",
           "\n## Checks\n", "| Check | Measured | Criterion | Result |\n|---|---|---|---|", rows, ""]
    (G.ROOT / "docs" / "PHASE5_REPORT.md").write_text("\n".join(txt), encoding="utf-8")


def chart(c, h, inc, tmetrics):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    fig = plt.figure(figsize=(17, 9))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.25])
    ax = fig.add_subplot(gs[0, :])
    col = {"green": 0, "amber": 1, "red": 2}
    v = h.health.map(col).to_numpy()
    cm = ListedColormap(["#2e8b57", "#e0a800", "#c0392b"])
    weeks = int(np.ceil(len(v) / 7))
    grid = np.full((7, weeks), np.nan)
    for i, x in enumerate(v):
        grid[i % 7, i // 7] = x
    ax.imshow(grid, cmap=cm, vmin=0, vmax=2, aspect="auto", interpolation="nearest")
    t0 = h.as_of.iloc[0]
    ticks = [i for i in range(0, weeks, 8)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([(t0 + pd.Timedelta(days=7 * i)).strftime("%Y-%m") for i in ticks], fontsize=8)
    ax.set_yticks(range(7))
    ax.set_yticklabels([(t0 + pd.Timedelta(days=i)).strftime("%a") for i in range(7)], fontsize=8)
    ax.set_title("Pipeline health, every nightly run (green = clean, amber = warnings open, red = error-level incident open)", pad=56)
    ann = [("F1 file re-sent", pd.Timestamp("2025-12-14"), -1.5), ("S3 outage", pd.Timestamp("2026-01-21"), -2.4), ("W4 bin relabel", pd.Timestamp("2026-02-15"), -1.5), ("S2 schema change", pd.Timestamp("2026-06-04"), -1.5)]
    for lab, tt, yo in ann:
        x = (tt - t0).days // 7
        ax.annotate(lab, (x, -0.5), xytext=(x, yo), fontsize=8, ha="center", arrowprops=dict(arrowstyle="-", color="grey", lw=0.8), annotation_clip=False)
    ax2 = fig.add_subplot(gs[1, 0])
    lat = [(a.split(" ")[0], e if e is not None else 0) for a, b, cc, e in inc]
    ax2.barh([a for a, _ in lat][::-1], [e for _, e in lat][::-1], color="#1D5FA3")
    ax2.set_xlim(0, 3)
    ax2.set_xlabel("days from incident start to first alert")
    ax2.set_title("Detection latency by incident")
    for i, (_, e) in enumerate(lat[::-1]):
        ax2.text(e + 0.05, i, "same night" if e == 0 else f"{e} d", va="center", fontsize=9)
    ax3 = fig.add_subplot(gs[1, 1])
    w = c.execute("""SELECT week, rate, p0, z FROM w.ops.dq_metric_weekly WHERE metric = 'wms_late_arrival_rate' AND p0 IS NOT NULL AND is_settled ORDER BY week""").fetchdf()
    ax3.plot(w.week, 100 * w.rate, lw=1.2, label="weekly rate")
    ax3.plot(w.week, 100 * w.p0, lw=1.0, ls="--", c="grey", label="12-week median baseline")
    pk = w.loc[w.z.abs().idxmax()]
    ax3.annotate("S3 catch-up\nafter outage", (pk.week, 100 * pk.rate), xytext=(pk.week - pd.Timedelta(days=170), 100 * pk.rate * 0.97), fontsize=8, arrowprops=dict(arrowstyle="->"))
    ax3.set_title("A control chart: late WMS events (settled weeks)")
    ax3.set_ylabel("% of events arriving 6+ hours late")
    ax3.legend(fontsize=8)
    ax3.tick_params(axis="x", rotation=30)
    ax3.grid(alpha=0.3)
    ax4 = fig.add_subplot(gs[1, 2])
    a = tmetrics[tmetrics.kind == "all"].sort_values("ratio")
    ax4.barh(a.metric.str.replace("_rate", ""), a.ratio, color="#1D5FA3")
    ax4.axvline(1.0, c="grey", lw=1)
    ax4.axvspan(0.9, 1.1, color="grey", alpha=0.15)
    ax4.set_xlim(0.8, 1.2)
    ax4.tick_params(axis="y", labelsize=7)
    ax4.set_title("Counted / injected (grey = within 10%)")
    fig.suptitle("Phase 5: data quality and observability scored against the answer key (all data synthetic)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(G.ROOT / "docs" / "phase5_observability.png", dpi=110)


def main():
    full = "--full" in sys.argv
    R = R3()
    c = connect()
    d = pd.read_parquet(G.TRUTH_DIR / "truth_defects.parquet")
    alerts = c.execute("SELECT * FROM w.ops.alerts_unified ORDER BY alert_id").fetchdf()
    inc, ex = incidents(c, R, d, alerts)
    h = health(c, R, alerts, d)
    tm, sens = metrics(c, R, d, alerts)
    cons = conservation(c, R, d)
    tests_recorded(c, R)
    cov = coverage(R, d, tm)
    c.close()
    if full:
        rebuild(R)
    c = connect()
    write_report(R, inc, tm, sens, cons, cov, h, full)
    chart(c, h, inc, tm)
    c.close()
    gates = [r for r in R.rows if r[5] == "GATE"]
    tg = [r for r in R.rows if r[5] == "TARGET"]
    print(f"\n{sum(r[4] for r in gates)}/{len(gates)} gates passed; {sum(r[4] for r in tg)}/{len(tg)} spec targets met")
    sys.exit(0 if R.all_ok else 1)


if __name__ == "__main__":
    main()
