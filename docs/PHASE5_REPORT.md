# System 1 — Phase 5 Report: Data Quality and Observability

Gates: **ALL PASS** (19/19). Spec targets: **1 of 2 met**, 1 missed (published as measured). Ops-layer determinism test was run in this pass.

## What the monitoring layer is

Nine automated checks, every night, for all 730 nights of history (catalog in `ops.dq_check_catalog`): schema drift (file held), stream freshness against each owner's promise, volume against the same weekday over the previous 8 weeks, byte-identical re-sent files, value-format drift (a column keeps its name but changes its shape), 20 weekly defect-rate control charts, layer-to-layer row conservation, dbt model tests, and reason-code governance. Everything lands in one alert log (`ops.alerts_unified`) and one nightly status (`ops.pipeline_health_daily`: green, amber, red).

Over the history the health view shows **713 green, 12 amber and 5 red nights**; red is reserved for error-level incidents.

## Incidents injected into the data and how they were caught

| Incident | Date | Raised as | Detection latency |
|---|---|---|---|
| S2 Carrier B changes its file layout | 2026-06-04 | schema-hold ERROR | same night |
| S3 Flagstaff WMS outage | 2026-01-21 | volume drop, then stream_stale ERROR | same night |
| F1 Carrier A re-sends 3 files | 2025-12-14 / 12-23 / 2026-05-31 | duplicate_file WARNING | same night |
| W4 Tucson bin labels change format | 2026-02-15 | value_format_drift WARNING | 2 day(s) |

Every alert in the log traces to one of those incidents; none is unexplained. The monitor tuning that produced that result is described in the Honest notes below.

## Weekly metrics against the injected rates

The weekly rate series are computed by the pipeline from the cleaned tables; the answer key says how many rows were actually injected. Where a metric counts every injected row the two agree closely; the four residual metrics measure what is left after repair, so they are not expected to match.

| Metric | Class | Pipeline counted | Injected | Ratio | Meaning |
|---|---|---|---|---|---|
| wms_duplicate_delivery_rate | W1 | 32,567 | 32,594 | 0.999 | counts every injected row |
| wms_late_arrival_rate | W2 | 45,569 | 45,094 | 1.011 | counts every injected row |
| wms_receipt_item_mismatch_rate | W5 | 514 | 517 | 0.994 | counts every injected row |
| wms_missing_ship_confirmation_rate | W6 | 2,791 | 2,697 | 1.035 | counts every injected row |
| legacy_ambiguous_date_rate | L2 | 142 | 142 | 1.000 | counts every injected row |
| legacy_unknown_vendor_rate | L4 | 429 | 429 | 1.000 | counts every injected row |
| legacy_unparseable_quantity_rate | L5 | 264 | 264 | 1.000 | counts every injected row |
| erp_nonpositive_quantity_rate | E3 | 910 | 908 | 1.002 | counts every injected row |
| erp_warehouse_missing_rate | E4 | 1,810 | 1,807 | 1.002 | counts every injected row |
| erp_case_quantity_rate | E5 | 9,810 | 9,218 | 1.064 | counts every injected row |
| erp_duplicate_line_rate | E2 | 3,171 | 3,189 | 0.994 | counts every injected row |
| erp_changed_after_entry_rate | E6 | 4,146 | 4,146 | 1.000 | counts every injected row |
| freight_delivery_time_invalid_rate | F4 | 64 | 64 | 1.000 | counts every injected row |
| freight_weight_missing_rate | F5 | 575 | 575 | 1.000 | counts every injected row |
| freight_duplicate_charge_rate | F7 | 196 | 197 | 0.995 | counts every injected row |
| count_case_vs_each_suspect_rate | X3 | 175 | 187 | 0.936 | counts every injected row |
| count_date_outside_month_rate | X5 | 75 | 83 | 0.904 | counts every injected row |
| receipt_quantity_variance_rate | C1 | 635 | 631 | 1.006 | counts every injected row |
| erp_superseded_item_rekeyed_rate | E1 | 4,378 | 4,901 | 0.893 | residual after repair |
| count_sku_unresolved_rate | X2 | 198 | 461 | 0.430 | residual after repair |
| freight_reference_unmatched_rate | F2 | 256 | 435 | 0.589 | residual after repair |
| wms_item_not_yet_linked_rate | W3 | 1,950 | 4,364 | 0.447 | residual after repair |

### What each control chart can and cannot see

A weekly rate raises an alert at the baseline (median of the previous 12 weeks) plus 5 binomial standard deviations. Rare defects have too few weekly rows to show a doubling; those are tracked, not alarmed.

| Metric | Baseline rate | Rows/week | Alerts at | Multiple of baseline | Catches a doubling |
|---|---|---|---|---|---|
| wms_late_arrival_rate | 2.51% | 19,377 | 3.07% | 1.22x | yes |
| wms_duplicate_delivery_rate | 1.79% | 19,728 | 2.26% | 1.26x | yes |
| erp_case_quantity_rate | 1.60% | 6,581 | 2.37% | 1.48x | yes |
| erp_changed_after_entry_rate | 0.69% | 6,581 | 1.20% | 1.74x | yes |
| erp_duplicate_line_rate | 0.51% | 6,622 | 0.94% | 1.86x | yes |
| wms_missing_ship_confirmation_rate | 0.49% | 5,962 | 0.94% | 1.92x | yes |
| erp_warehouse_missing_rate | 0.28% | 6,581 | 0.61% | 2.16x | no |
| erp_nonpositive_quantity_rate | 0.15% | 6,581 | 0.38% | 2.60x | no |
| legacy_unknown_vendor_rate | 6.19% | 115 | 17.43% | 2.81x | no |
| receipt_quantity_variance_rate | 0.88% | 722 | 2.62% | 2.97x | no |
| freight_weight_missing_rate | 1.87% | 297 | 5.80% | 3.10x | no |
| wms_receipt_item_mismatch_rate | 0.80% | 638 | 2.56% | 3.20x | no |
| freight_reference_unmatched_rate | 0.83% | 297 | 3.47% | 4.17x | no |
| legacy_unparseable_quantity_rate | 0.26% | 818 | 1.15% | 4.44x | no |
| count_sku_unresolved_rate | 0.82% | 238 | 3.73% | 4.57x | no |
| count_case_vs_each_suspect_rate | 0.73% | 238 | 3.50% | 4.77x | no |
| freight_duplicate_charge_rate | 0.24% | 672 | 1.19% | 4.93x | no |
| freight_delivery_time_invalid_rate | 0.22% | 297 | 1.59% | 7.15x | no |
| legacy_ambiguous_date_rate | 0.06% | 818 | 0.51% | 7.91x | no |

## Quarantine, conservation and governance

Quarantine false positives: 0 good rows rejected of 711,946. Review-queue rows by who owns the action:

| Owner | Rows |
|---|---|
| customer service | 1,487 |
| Albuquerque branch | 690 |
| receiving | 635 |
| item master owner | 578 |
| branch manager | 273 |
| freight | 256 |
| warehouse ops | 152 |
| purchasing | 107 |

## Detection coverage by defect class

What an operator would see for each injected class. The last column is metric ÷ injected where a metric counts the class.

| Class | Injected | Operator sees | Where | Metric/injected |
|---|---|---|---|---|
| C1 | 631 | review queue + weekly metric | C1_RECEIPT_QUANTITY_VARIANCE; receipt_quantity_variance_rate | 1.01 |
| C3 | 144 | review queue | C3_TRANSFER_OUT_WITHOUT_IN (in-transit exceptions) |  |
| E1 | 4,901 | row flag + weekly metric (not charted: follows item launches) | flag_item_remapped; erp_superseded_item_rekeyed_rate | 0.89 |
| E2 | 3,734 | weekly metric + review queue (near duplicates) | erp_duplicate_line_rate; E2_NEAR_DUPLICATE_ORDER_LINE | 0.99 |
| E3 | 908 | quarantine reason + weekly metric | E3_QUANTITY_NOT_POSITIVE; erp_nonpositive_quantity_rate | 1.00 |
| E4 | 1,807 | weekly metric + review queue when unresolved | erp_warehouse_missing_rate; E4_WAREHOUSE_UNKNOWN | 1.00 |
| E5 | 9,218 | weekly metric | erp_case_quantity_rate | 1.06 |
| E5b | 666 | quarantine reason | E5B_NO_CASE_SIZE |  |
| E6 | 4,146 | weekly metric | erp_changed_after_entry_rate | 1.00 |
| F1 | 3 | alert | duplicate_file |  |
| F2 | 435 | review queue + weekly metric | F2_REFERENCE_UNMATCHED; freight_reference_unmatched_rate | 0.59 |
| F4 | 64 | weekly metric | freight_delivery_time_invalid_rate | 1.00 |
| F5 | 854 | weekly metric | freight_weight_missing_rate | 1.00 |
| F7 | 197 | weekly metric + recoverable-dollar flag | freight_duplicate_charge_rate | 0.99 |
| L1 | 3,363 | review queue | L1_ITEM_AMBIGUOUS |  |
| L2 | 142 | weekly metric | legacy_ambiguous_date_rate | 1.00 |
| L4 | 429 | weekly metric | legacy_unknown_vendor_rate | 1.00 |
| L5 | 264 | quarantine reason + weekly metric | L5_QUANTITY_UNPARSEABLE; legacy_unparseable_quantity_rate | 1.00 |
| L6 | 7 | review queue | L6_VENDOR_WEAK_MATCH |  |
| S2 | 1 | alert (ERROR, file held) | load_or_schema, stream_stale |  |
| S3 | 652 | alerts + weekly metric | volume_anomaly, stream_stale, wms_late_arrival_rate |  |
| U1 | 160 | none: undetectable per row by design | visible only as count variance |  |
| U2 | 31 | none: undetectable by design | visible only as count variance |  |
| U3 | 1,755 | none as a cause: unrecorded shrink | visible as count variance and stock confidence |  |
| W1 | 32,594 | weekly metric | wms_duplicate_delivery_rate | 1.00 |
| W2 | 45,094 | weekly metric | wms_late_arrival_rate | 1.01 |
| W3 | 4,364 | row flag + weekly metric (not charted: follows item launches) | item_linked_late; wms_item_not_yet_linked_rate | 0.45 |
| W4 | 1 | alert | value_format_drift |  |
| W5 | 517 | review queue + weekly metric | W5_RECEIPT_ITEM_UNRESOLVED; wms_receipt_item_mismatch_rate | 0.99 |
| W6 | 2,697 | weekly metric | wms_missing_ship_confirmation_rate | 1.03 |
| X1 | 34 | none: header variants absorbed by approved contract versions | contract versions |  |
| X2 | 461 | review queue + weekly metric | sku_unresolved; count_sku_unresolved_rate | 0.43 |
| X3 | 187 | weekly metric | count_case_vs_each_suspect_rate | 0.94 |
| X4 | 144 | none: stripped silently (cosmetic) | n/a |  |
| X5 | 83 | quarantine reason + weekly metric | date_outside_sheet_month; count_date_outside_month_rate | 0.90 |
| X6 | 88 | review queue (one item per conflicting price pair) | X6_PRICE_CONFLICT |  |

## Honest notes

- **Tuning disclosure.** The first version of the weekly control charts raised 25 false alarms, because week-to-week calendar effects (items being superseded, holiday weeks) and late-arriving corrections looked like quality shifts. I changed the design, not the target: a median baseline instead of a mean, judge only weeks older than 14 days, a 12-week burn-in of weeks with at least 100 rows, and leave four calendar-driven rates uncharted. That removed all false alarms; the cost is that a defect shift is seen up to two weeks late and that small shifts in rare defects are invisible (table above).

- **Volume alerts exclude holiday weekends** (seed `closure_days`); a real outage that coincides with a holiday would be missed by the volume monitor, though freshness would still catch it.

- **Unrecorded shrink (U3) has no monitor.** No source system records it, so the only signal is a count variance, which is why stock confidence and count frequency matter more than any pipeline check.

- **5 of 36 defect classes have no operator-visible signal by design** (U1, U2, U3, X1, X4): undetectable per row (U1-U3) or absorbed silently by a documented rule (X1, X4). The incident detectors were scored on the answer key and the weekly metrics on injected totals; the numbers above are measured, not asserted.

- **Weekly-rate alerts are a slow second line, not the first responder.** A week is judged only once it is more than 14 days old, so in live running such an alert appears about two weeks after the shift; the replay stamps it with the end of the affected week. Fast detection comes from freshness, volume, duplicate-file and format monitors.


## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| S2 carrier schema change: detected in the same nightly run, file held, not loaded silently | first ERROR on 2026-06-04 vs change on 2026-06-04; 4 files held; none loaded in the changed layout | same night | PASS |
| S2: every changed file was held and later released once the contract was approved | 4 of the 4 changed files held; 4 loaded after release on 2026-06-08 | 4 held, 4 released | PASS |
| S3 Flagstaff WMS outage: raised an alert within 2 days of the first quiet day | first alert 0 day(s) after the outage began (volume_anomaly 2026-01-21, stream_stale 2026-01-23, volume_anomaly 2026-01-24, dq_rate_out_of_control 2026-01-25) | <= 2 days | PASS |
| S3: the silent stream was escalated to ERROR (stock-critical stream) | 1 ERROR stream_stale alert(s) on wms:WH-03, first 2026-01-23 | >= 1 | PASS |
| F1 re-sent carrier files: every byte-identical copy flagged | 3 of 3 flagged; extra duplicate-file alerts: 0 | all, no extras | PASS |
| W4 bin label change (no schema change, same columns): detected within 7 days | change 2026-02-15; alert 2026-02-17 (2 days); wms.bin for WH-02 switched from pattern A-12-3 to A12-03 | <= 7 days | PASS |
| no unexplained alerts: every alert traces to an injected incident (false-alarm rate) | 13 of 13 alerts explained; unexplained: 0 | 0 unexplained | PASS |
| alert noise: nights with a non-green status that no incident explains | 0 of 730 nights (0.00%) | reported | INFO |
| nights by status over the 730-night history | green 713, amber 12, red 5 | reported | INFO |
| S2 carrier schema change: the health view is not green on the nights it happened | 4 of 4 nights non-green (4 red) between 2026-06-04 and 2026-06-07 | >= 1 red night | PASS |
| S3 Flagstaff outage: the health view is not green on the nights it happened | 2 of 3 nights non-green (1 red) between 2026-01-21 and 2026-01-23 | >= 1 red night | PASS |
| every night inside an incident window shows non-green | 6 of 7 incident nights non-green; green night(s) inside the window: S3 Flagstaff outage x1 | 100% | MISSED |
| every red night has an error-level incident behind it (red is not cosmetic) | 5 red nights: 2026-01-23, 2026-06-04, 2026-06-05, 2026-06-06, 2026-06-07 | all red nights have open_errors > 0 or failed files | PASS |
| files ever held for schema drift | 4 | reported | INFO |
| metrics that count every injected row agree with the answer key within 10% | 18 of 18 within 10% (range 0.904 to 1.064) | all | PASS |
| metrics matching the answer key within 1% | 13 of 18 | reported | INFO |
| residual metrics (what is left after repair; not expected to equal the injected total) | erp_superseded_item_rekeyed_rate 4,378 vs 4,901 injected; count_sku_unresolved_rate 198 vs 461 injected; freight_reference_unmatched_rate 256 vs 435 injected; wms_item_not_yet_linked_rate 1,950 vs 4,364 injected | reported | INFO |
| control-chart sensitivity (a weekly rate must reach baseline + 5 sigma) | median alert threshold 2.97x baseline; a doubling of the rate is caught for 6 of 19 charted metrics; the rest are too rare per week to see a doubling | reported | INFO |
| control charts raised no alert outside the Flagstaff catch-up window | 1 metric(s) ever out of control: wms_late_arrival_rate; outside S3: 0 | 0 | PASS |
| rows are conserved between layers: nothing disappears without a recorded reason | 9 of 9 layer checks balance exactly (largest absolute difference 0) | all balance | PASS |
| SPEC target: quarantine false-positive rate (good rows wrongly rejected) <= 1% | 0 good rows rejected of 711,946 good rows = 0.0000% (0 of 2,486 quarantined rows were not defective; legacy 0/690, counts 0/273, orders 0/1523) | <= 1% | MET |
| no quarantined row is a good row (precision of the quarantine) | 2,486 of 2,486 quarantined rows carry an injected defect (100.00%) | >= 98% | PASS |
| every review-queue row carries a governed reason code (owner, severity, suggested action) | 4,178 rows over 14 reason codes; ungoverned rows: 0 | 0 ungoverned | PASS |
| reason-code registry | 14 codes, 0 never used in this history | reported | INFO |
| the latest dbt test run is recorded in the warehouse and every test passes | 69 of 69 recorded tests pass | all pass, at least 50 recorded | PASS |
| a health row exists for every nightly run | 730 nights from 2024-10-01 to 2026-09-30 | 730 | PASS |
| checks documented in the catalog | 9 | reported | INFO |
| every injected defect class is accounted for in the coverage matrix | 36 classes mapped; unmapped: none | none unmapped | PASS |
| classes with no operator-visible signal | 5 of 36 (U1, U2, U3, X1, X4); 2,124 of 120,776 injected defects (1.8%), nearly all of it the invisible shrink (U3) | reported | INFO |
| rebuilding the ops layer reproduces identical tables | 11/11 tables identical (11s) | all identical | PASS |
