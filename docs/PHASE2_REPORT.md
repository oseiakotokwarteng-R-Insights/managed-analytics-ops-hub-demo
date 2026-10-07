# System 1 — Phase 2 Report: The Five Source Systems

Result: **ALL CHECKS PASS** (50/50).

Source data: 9,065 files, 771 MB, 120,776 logged defects.

## Source inventory

| System | Files | Content digest |
|---|---|---|
| erp | 2,516 | c3caec6f0d2c1a95 |
| freight | 2,625 | 859076cff6f43ed3 |
| legacy | 107 | 63e6ccfeac5f6c4d |
| spreadsheets | 171 | 67d60f6b3b19721a |
| wms | 3,646 | 4727da85561f7db3 |

## Naive-join evidence

| Join | Naive result | Why |
|---|---|---|
| ERP item_no = WMS item_id | 0% (different identifier systems: text SKU vs integer id) | needs the ERP link table, and new items are linked up to 35 days late (W3) |
| ERP item_no = legacy item_code | 0 matching rows | 8-char codes need a crosswalk; 6% are ambiguous across revisions |
| ERP order_no = carrier shipper_ref (Carrier A, 120-day sample) | 98.5% exact | case, hyphen, padding and typo variants (F2) |
| ERP item_no = count-sheet SKU | 98.1% exact | typed SKUs (X2), valid-but-wrong swaps (U2) |
| timestamps across the five systems | 6 conventions | ERP naive local per warehouse; WMS UTC ISO-8601; Carrier A epoch ms; Carrier B local + text offset; legacy date-only text in 2 formats; sheets free text |
| units of measure | 1.5% of ERP line rows in cases | conversion factor lives in the item master and is missing for some items (E5b) |

## Defects logged

| Code | System | Count |
|---|---|---|
| C1 | ERP | 631 |
| C3 | CROSS | 144 |
| E1 | ERP | 4,901 |
| E2 | ERP | 3,734 |
| E3 | ERP | 908 |
| E4 | ERP | 1,807 |
| E5 | ERP | 9,218 |
| E5b | ERP | 666 |
| E6 | ERP | 4,146 |
| F1 | FREIGHT | 3 |
| F2 | FREIGHT | 435 |
| F4 | FREIGHT | 64 |
| F5 | FREIGHT | 854 |
| F7 | FREIGHT | 197 |
| L1 | LEGACY | 3,363 |
| L2 | LEGACY | 142 |
| L4 | LEGACY | 429 |
| L5 | LEGACY | 264 |
| L6 | LEGACY | 7 |
| S2 | FREIGHT | 1 |
| S3 | WMS | 652 |
| U1 | SHEETS | 160 |
| U2 | SHEETS | 31 |
| U3 | TRUTH | 1,755 |
| W1 | WMS | 32,594 |
| W2 | WMS | 45,094 |
| W3 | WMS | 4,364 |
| W4 | WMS | 1 |
| W5 | WMS | 517 |
| W6 | WMS | 2,697 |
| X1 | SHEETS | 34 |
| X2 | SHEETS | 461 |
| X3 | SHEETS | 187 |
| X4 | SHEETS | 144 |
| X5 | SHEETS | 83 |
| X6 | SHEETS | 88 |

## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| five systems present in five different native formats | ERP csv (2,516 files), WMS jsonl (3,646), freight json+csv (2,625), legacy csv (107), xlsx (171) | all > 0 | PASS |
| volumes | erp lines (all versions) 645,442; erp headers 208,319; erp po lines 146,315; wms events 1,844,284; legacy rows 81,234 | WMS ~1.8M, ERP lines ~0.65M | PASS |
| E2 duplicate lines from re-keyed orders | 3,734 of 608,957 = 0.61% (target 0.60%) | within 4 sigma of 0.60% | PASS |
| E3 zero/negative quantity | 908 of 608,957 = 0.15% (target 0.15%) | within 4 sigma of 0.15% | PASS |
| E4 ship-from warehouse null/invalid | 1,807 of 608,957 = 0.30% (target 0.30%) | within 4 sigma of 0.30% | PASS |
| E5 lines in cases (legit) | 9,218 of 608,957 = 1.51% (target 1.50%) | within 4 sigma of 1.50% | PASS |
| E6 quantity changed after shipment | 4,146 of 608,957 = 0.68% (7% of eligible shipped lines whose change date is in history) | within 5 sigma of 0.68% | PASS |
| E1 successor SKU keyed as predecessor | 4,901 = 0.80% | 0.75-0.85% (candidate-limited) | PASS |
| W1 duplicate events (at-least-once delivery) | 32,594 of 1,802,663 = 1.81% (target 1.80%) | within 4 sigma of 1.80% | PASS |
| W2 late / out-of-order events | 45,094 of 1,802,663 = 2.50% (target 2.50%) | within 4 sigma of 2.50% | PASS |
| W3 events for items not yet linked to a WMS id (natural) | 4,364 = 0.24% | 0.15-0.35% (natural result of a 0-35 day link lag) | PASS |
| W5 receipts keyed under the wrong item | 517 of 65,314 = 0.79% (target 0.80%) | within 4 sigma of 0.80% | PASS |
| W6 ship confirmations missing (line-level drop) | 2,697 of 560,670 = 0.48% (target 0.50%) | within 5 sigma of 0.50% | PASS |
| C3 transfers recorded one-sided | 144 of 11,848 = 1.22% (target 1.20%) | within 4 sigma of 1.20% | PASS |
| C1 POs whose ERP receipt disagrees with the WMS | 1.86% of 33,541 POs | 1.5-2.5% | PASS |
| F2 carrier reference mangled | 435 of 28,183 = 1.54% (target 1.50%) | within 4 sigma of 1.50% | PASS |
| F4 delivery before pickup / impossible transit | 64 of 28,183 = 0.23% (target 0.20%) | within 4 sigma of 0.20% | PASS |
| F5 weight or pieces missing | 854 of 28,183 = 3.03% (target 3.00%) | within 4 sigma of 3.00% | PASS |
| F7 duplicate charge line on a Carrier A shipment | 197 of 18,181 = 1.08% (target 1.00%) | within 4 sigma of 1.00% | PASS |
| F1 carrier re-sent whole prior-day files | 3 | exactly 3 | PASS |
| S2 Carrier B schema change | 1 event, 106 files in new schema | 1 event on 2026-06-04 | PASS |
| S3 WMS outage Flagstaff | 652 events delayed 36-60h | > 400 | PASS |
| L4 orphan vendor ids on receipts | 429 of 8,418 = 5.10% (target 5.00%) | within 4 sigma of 5.00% | PASS |
| L5 unparseable numerics | 264 of 81,234 = 0.32% (target 0.30%) | within 4 sigma of 0.30% | PASS |
| L2 day-ambiguous dates (blank terminal and day <= 12) | 142 = 0.17% | 0.1-0.3% | PASS |
| L6 duplicate vendors | 7 pairs (5 strong, 2 weak) | exactly 7 | PASS |
| X2 count rows with SKU typos | 461 of 24,485 = 1.88% (target 2.00%) | within 4 sigma of 2.00% | PASS |
| X3 cases counted but entered as each | 187 of 24,485 = 0.76% (target 0.80%) | within 4 sigma of 0.80% | PASS |
| X5 count dated wrong month/year | 83 of 24,485 = 0.34% (target 0.40%) | within 4 sigma of 0.40% | PASS |
| X6 conflicting price overrides | 88 of 6,091 = 1.44% (of rows including the conflicts) | within 4 sigma of 1.48% | PASS |
| X1 files with non-standard header names | 34 of 144 = 24% | ~35% (3-sigma band 23-47%) | PASS |
| U1/U2/U3 deliberately undetectable classes present | U1 160, U2 31, U3 1,755 | all > 0 | PASS |
| ERP: distinct order lines = truth lines + logged duplicates | 613,308 vs 609,574 + 3,734 | equal | PASS |
| ERP: every line with NO logged defect equals the truth (sku, qty, shipped, price) | 0 mismatches of 588,162 clean lines | 0 | PASS |
| ERP: each logged defect is present in the data exactly as logged (E1,E3,E4,E5,E5b,E6) | E1 4901/4901, E3 908/908, E4 1807/1807, E5 9218/9218, E5b 582/582, E6 4146/4146 | all rows verified | PASS |
| ERP POs: every received line with no logged C1 defect equals the truth | 0 mismatches | 0 | PASS |
| stock identity: truth - system book == logged unrecorded effects - posted count adjustments (all SKU-warehouse pairs, WMS + legacy) | 0 mismatches of 12,708 pairs | 0 | PASS |
| record accuracy implied by the sources (informational): share of pairs where the book equals physical stock at the cutoff | 82.6% exact; 2,210 pairs off | reported | PASS |
| Carrier A: every truth shipment is in the feed; refs, weights, delivery dates match except logged F2/F4/F5 | 18,181/18,181 present; ref 0, weight 0, delivery-date 0 mismatches | 0 mismatches | PASS |
| Carrier A: invoiced charges = truth charges + logged F7 duplicates, per shipment | 0 mismatches of 18,147 invoiced | 0 | PASS |
| S4 double-billed freight: recoverable dollars planted (informational) | $12,991 across 197 shipments | reported | PASS |
| Carrier B: all shipments present; weights equal the truth across BOTH schemas (weight_lb and wt_lbs) | 10,002/10,002 present, 0 weight mismatches; schema cols new=['delivery_type', 'dim_weight', 'service_level', 'wt_lbs'] | 0 mismatches, new columns present | PASS |
| Carrier B: invoiced charges equal truth charges per shipment | 0 mismatches | 0 | PASS |
| F1: re-sent files are exact copies of the previous day's file | 3 resends, 0 differing | 3, 0 differing | PASS |
| Spreadsheets: every truth count appears as exactly one sheet row | 24,485 sheet rows vs 24,485 counts | equal | PASS |
| Spreadsheets: every row with no logged defect reproduces the true count (sku, date, quantity) | 0 mismatches of 23,565 clean rows | 0 | PASS |
| X2 SKU typos: share recoverable by a unique single edit (the rest must go to review) | 56% of 461 | reported (>= 40%) | PASS |
| no two systems integrate by key equality (item, order-reference and SKU joins all lose rows) | ERP item_no = WMS item_id: 0% (different identifier systems: text SKU vs integer id); ERP item_no = legacy item_code: 0 matching rows; ERP order_no = carrier shipper_ref (Carrier A, 120-day sample): 98.5% exact; ERP item_no = count-sheet SKU: 98.1% exact | each < 100% | PASS |
| heterogeneity: timestamp conventions and units of measure | 6 timestamp conventions; CS/EA mix | >= 4 conventions | PASS |
| rebuilding from the same seed reproduces every source file bit-for-bit (xlsx by parsed content) | 5/5 systems identical; sheets identical; defect log identical | all identical | PASS |
