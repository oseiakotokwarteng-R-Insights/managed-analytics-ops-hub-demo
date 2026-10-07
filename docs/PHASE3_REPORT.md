# System 1 — Phase 3 Report: Raw-Layer Ingestion

Result: **ALL CHECKS PASS** (23/23). Backfill-equivalence test was run in this pass.

Nightly runs: OK: 726, OK_WITH_HELD_FILES: 4.

## What is loaded

| Raw table (by contract) | Files | Rows | Arrival window |
|---|---|---|---|
| carrier_a_shipments | 733 | 68,947 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| carrier_b_charges | 521 | 23,880 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| carrier_b_shipments | 641 | 10,002 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| carrier_b_tracking | 730 | 56,886 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| erp_customer_master | 1 | 1,600 | 2024-10-01 00:00:00 to 2024-10-01 00:00:00 |
| erp_item_master | 1 | 2,800 | 2024-10-01 00:00:00 to 2024-10-01 00:00:00 |
| erp_po_header | 585 | 66,418 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| erp_po_line | 585 | 146,315 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| erp_sales_order_header | 612 | 208,319 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| erp_sales_order_line | 730 | 645,442 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |
| erp_vendor_master | 1 | 140 | 2024-10-01 00:00:00 to 2024-10-01 00:00:00 |
| erp_warehouse_master | 1 | 6 | 2024-10-01 00:00:00 to 2024-10-01 00:00:00 |
| legacy_inv_trans | 104 | 80,754 | 2024-10-06 00:00:00 to 2026-09-27 00:00:00 |
| legacy_item_cost | 1 | 14,000 | 2024-10-01 00:00:00 to 2024-10-01 00:00:00 |
| legacy_vendor | 1 | 147 | 2024-10-01 00:00:00 to 2024-10-01 00:00:00 |
| sheet_cells_count | 138 | 27,777 | 2024-11-03 00:00:00 to 2026-09-03 00:00:00 |
| sheet_cells_price | 26 | 5,987 | 2024-08-07 00:00:00 to 2026-09-07 00:00:00 |
| wms_events | 3,646 | 1,844,284 | 2024-10-01 00:00:00 to 2026-09-30 00:00:00 |

## Incident replay: Carrier B schema change (S2)

| Detected | File | Change | Action | Released |
|---|---|---|---|---|
| 2026-06-04 00:00:00 | shipments_20260604.csv | missing service,weight_lb; new delivery_type,dim_weight,service_level,wt_lbs | held, alert raised | 2026-06-08 00:00:00 (loaded under contract v2) |
| 2026-06-05 00:00:00 | shipments_20260605.csv | missing service,weight_lb; new delivery_type,dim_weight,service_level,wt_lbs | held, alert raised | 2026-06-08 00:00:00 (loaded under contract v2) |
| 2026-06-06 00:00:00 | shipments_20260606.csv | missing service,weight_lb; new delivery_type,dim_weight,service_level,wt_lbs | held, alert raised | 2026-06-08 00:00:00 (loaded under contract v2) |
| 2026-06-07 00:00:00 | shipments_20260607.csv | missing service,weight_lb; new delivery_type,dim_weight,service_level,wt_lbs | held, alert raised | 2026-06-08 00:00:00 (loaded under contract v2) |

## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| every file that had arrived by 2026-09-30 is loaded | 9,057 of 9,057 files; 8 not yet arrived (live window) | all | PASS |
| raw row counts equal an independent recount of the source files (every table) | 3,203,704 rows over 17 tables; 0 tables differ  | 0 differ | PASS |
| audit trail adds up: sum of per-file rows_loaded = rows in raw | 3,203,704 vs 3,203,704 | equal | PASS |
| nothing left held or failed at the end of history | {'LOADED': 9057} | only LOADED | PASS |
| re-running the whole history changes nothing | loaded 0 files, 0 rows; content hashes identical; no new audit rows: True | 0 / 0 / identical | PASS |
| registry matches the disk: re-hashing every loaded file reproduces its recorded sha256 | 9,057 of 9,057 match (2s) | all | PASS |
| every raw row traces to a loaded file (lineage) | 0 orphan rows | 0 | PASS |
| no time travel: every file is loaded after it arrived | minimum arrival-to-load gap 1 day(s) | >= 1 | PASS |
| no load failures across 730 nightly runs | 0 | 0 | PASS |
| the Carrier B schema change was detected on the day each file arrived | 4 files held; detected on ['2026-06-04', '2026-06-05', '2026-06-06', '2026-06-07']; expected 4 files dated 06-04..06-07 | all new-schema files before approval | PASS |
| held files released when the new contract was approved, none lost | 4/4 resolved on ['2026-06-08'] | all resolved 2026-06-08 | PASS |
| raw table evolved exactly once, by approved contract, and nothing else drifted | 1 evolution (service_level,delivery_type,wt_lbs,dim_weight); kinds {'BREAKING': 4, 'EVOLUTION': 1} | 1 evolution, 0 other | PASS |
| no open alerts at the end | 0 open of 4 raised | 0 open | PASS |
| no row mixes the two schemas: old rows fill weight_lb, new rows fill wt_lbs | v1 rows 8,111, v2 rows 1,682, mixed 0 | mixed = 0 | PASS |
| no new-schema file loaded before the contract was approved | first v2 load 2026-06-09 | >= 2026-06-09 (run after 06-08 approval) | PASS |
| WMS duplicate deliveries are preserved (dedupe is staging's job) | 32,567 duplicate copies in raw vs 32,594 injected (27 copies were still in flight at the end of history) | raw = injected minus in-flight (<= 0.2%) | PASS |
| unparseable legacy quantities are preserved as text | 264 non-numeric qty values in raw vs 264 injected | equal | PASS |
| late-arriving WMS events are loaded with their original timestamps | 45,569 distinct events first delivered >= 6h after they happened vs 45,724 logged (W2 union S3); 155 of the logged ones were still in flight at the end of history (all 235 undelivered events) | raw = logged minus in-flight | PASS |
| whitespace and formatting quirks survive raw untouched | 32,595 legacy item codes carry padding | > 0 | PASS |
| spreadsheet cells keep their types (text vs number vs date vs formula) | 9 cell-type patterns; 1,656 formula rows, 22,920 rows with true date cells | formulas and dates visible | PASS |
| nightly runs recorded for the whole history | 730 runs; slowest 185.0s; total 544s; database 574 MB | 730 runs | PASS |
| ingestion test suite (crash safety, changed files, drift, late files, corrupt files, truth guard) | 24 passed in 77.83s (0:01:17) | all pass | PASS |
| one-shot backfill and 730 nightly runs produce identical raw content (every table) | 17/17 tables identical; one-shot 393s, status OK | all identical | PASS |
