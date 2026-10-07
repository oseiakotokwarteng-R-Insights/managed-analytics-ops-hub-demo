# System 1 — Phase 4 Report: Modeling and the Stock Table

Gates: **ALL PASS** (38/38). Spec targets: **2 of 3 met**, 1 missed (published as measured). Rebuild-determinism test was run in this pass.

## Headline: how good is the stock table?

On 9,276,840 SKU-warehouse-days, compared with the hidden physical truth: the source systems' recorded book is exact on **87.4%**; the reconstructed estimate on **95.1%** (+7.7 points). Excluding the 8.0% of days flagged suspect, it is exact on **97.90%** against the spec's 98% target.

| Confidence tier | Exact | Pair-days |
|---|---|---|
| carried | 97.70% | 6,677,101 (72.0%) |
| suspect | 63.05% | 738,367 (8.0%) |
| verified | 98.64% | 1,861,372 (20.1%) |

### Accuracy decays with time since the last count (days not flagged suspect)

| Days since last count | Exact | Pair-days |
|---|---|---|
| never counted | 99.2% | 3,291,875 |
| 0-30 | 98.9% | 674,219 |
| 31-90 | 98.5% | 1,187,153 |
| 91-180 | 97.7% | 1,358,729 |
| 181-365 | 96.5% | 1,358,048 |
| >365 | 93.0% | 668,449 |

### What the remaining errors are (wrong and not flagged suspect)

| Cause (from the answer key) | Pair-days | Share |
|---|---|---|
| unrecorded shrink | 121,106 | 67.6% |
| Albuquerque loss (S1) | 46 | 0.0% |
| mis-keyed receipt (W5) | 417 | 0.2% |
| transfer in-side missing (C3) | 1,042 | 0.6% |
| bad count row used as anchor | 27,591 | 15.4% |
| more than one cause | 27,087 | 15.1% |
| no injected cause (modelling gap) | 1,741 | 1.0% |

Shrink and similar losses are recorded by no system until a count finds them, so no model can recover them earlier; the fix is a counting policy, not more modeling.

## Model volumes

| Model | Rows |
|---|---|
| fct_stock_movement | 728,935 |
| fct_order_line | 613,308 |
| fct_count | 23,541 |
| fct_shipment | 28,183 |
| fct_freight_charge | 63,888 |
| fct_po_line | 73,858 |
| mart_stock_daily | 9,289,548 |
| review_queue | 4,178 |

## Review queue (decisions the pipeline would not make alone)

| System | Reason | Rows |
|---|---|---|
| ERP | E3_QUANTITY_NOT_POSITIVE | 910 |
| ERP | C1_RECEIPT_QUANTITY_VARIANCE | 635 |
| ERP | E5B_NO_CASE_SIZE | 578 |
| ERP | E2_NEAR_DUPLICATE_ORDER_LINE | 542 |
| LEGACY | L1_ITEM_AMBIGUOUS | 426 |
| LEGACY | L5_QUANTITY_UNPARSEABLE | 264 |
| FREIGHT | F2_REFERENCE_UNMATCHED | 256 |
| SHEETS | sku_unresolved | 198 |
| WMS | C3_TRANSFER_OUT_WITHOUT_IN | 150 |
| SHEETS | X6_PRICE_CONFLICT | 105 |
| SHEETS | date_outside_sheet_month | 75 |
| ERP | E4_WAREHOUSE_UNKNOWN | 35 |
| WMS | W5_RECEIPT_ITEM_UNRESOLVED | 2 |
| LEGACY | L6_VENDOR_WEAK_MATCH | 2 |

## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| the mart covers every SKU-warehouse pair on every day | 9,276,840 compared of 12,708 pairs x 730 days = 9,276,840 | all | PASS |
| the estimate beats the systems' own recorded book | recorded book exact on 87.40% of pair-days, evidence-corrected ledger 89.42%, reconstructed estimate 95.13% | estimate >= recorded + 5 points | PASS |
| the estimate is right on most days overall | 95.13% of all 9,276,840 pair-days exact | >= 94% | PASS |
| the 'suspect' flag is informative: wrong days concentrate in it | 36.9% of suspect days are wrong vs 2.10% of the rest (18x) | >= 10x | PASS |
| SPEC target: estimate exact on >= 98% of pair-days, excluding unresolved (suspect) items | 97.90% exact on the 92.0% of pair-days not flagged suspect | >= 98% | MISSED |
| calibration by confidence tier (informational) | carried: 97.70% exact on 72.0% of days; suspect: 63.05% exact on 8.0% of days; verified: 98.64% exact on 20.1% of days | reported | PASS |
| accuracy decays with time since the last count (informational) | never counted: 99.2%; 0-30 d: 98.9%; 31-90 d: 98.5%; 91-180 d: 97.7%; 181-365 d: 96.5%; >365 d: 93.0% | reported | PASS |
| every WMS event resolves to an ERP item, and the mapping agrees with the answer key | 0 unresolved events; 0 wrong mappings | 0 / 0 | PASS |
| the documented legacy code scheme reproduces every legacy code | 0 of 2,800 items differ | 0 | PASS |
| SPEC target: legacy code crosswalk precision >= 99.5% | shared-code rows: 2,918 of 2,919 resolved are correct = 99.97% precision (1 wrong) | >= 99.5% | MET |
| SPEC target: legacy code crosswalk recall >= 97% (rest to review, never guessed) | 99.47% of all 80,754 legacy rows resolved (428 to review); of the 253 date-ambiguous rows, 87 correct, 165 to review | >= 97% | MET |
| L2 day-ambiguous legacy dates are settled correctly using the dump week and ERP evidence | 142 of 142 correct | >= 95% | PASS |
| W5 mis-keyed receipts: re-assigned using the PO, precision and recall | 511 of 517 corrected right (98.8% recall); 2 sent to review, 3 not detected; 0 wrongly touched | recall >= 90%, no false positives | PASS |
| L6 duplicate vendors: strong matches merged automatically, weak matches sent to review | strong merged correctly 5/5; weak to review 2/2 | 5/5 and 2/2 | PASS |
| E1 successor items keyed as predecessors: remapped to the true item | 4378 of 4901 correct = 89.3% (the rest are Albuquerque orders, where no WMS evidence exists) | >= 85% | PASS |
| E1 remapping never makes a correct item wrong | 0 wrong remaps | 0 | PASS |
| E2 re-keyed duplicates: exact ones dropped, near-matches flagged, nothing else dropped | 3171 dropped of 3189 exact duplicates (99.4%); 542 near-matches flagged; 0 real lines wrongly dropped | recall >= 95%, 0 false drops | PASS |
| E3 zero/negative quantities: excluded | 908 of 908 | >= 98% | PASS |
| E4 missing/invalid ship-from warehouse: filled from the customer default or a sibling line | 1773 of 1807 filled correctly = 98.1%; 34 left to review | >= 95% (wrong fills must be 0) | PASS |
| E5 quantities entered in cases: converted to units correctly | 9218 of 9218 | 100% | PASS |
| E5b cases with no case size on the item: excluded, not guessed | 578 of 582 | >= 98% | PASS |
| E6 quantity changed after shipment: both the original and the current quantity kept, original equals the truth | 4146 of 4146 | 100% | PASS |
| every cleaned order line (kept, not a duplicate) equals the truth on item, original quantity and warehouse | 607,532 of 608,054 = 99.914% | >= 99.9% | PASS |
| W6/C2 dropped ship confirmations: shipments inferred from PICK/PACK plus ERP | 2658 of 2659 dropped lines recovered (100.0% recall); 95 extra inferences (shipments not yet confirmed at the end of history) | recall >= 95% | PASS |
| C3 one-sided transfers: missing out-side inferred, missing in-side listed as in-transit exceptions | out-side inferred 69 of 69 logged (0 extra); in-side exceptions 75 of 75 logged (75 extra) | both >= 90% | PASS |
| C1 ERP receipt quantities that disagree with the warehouse: detected | 631 of 631 logged (100.0%); 4 extra variances | recall >= 95% | PASS |
| L4 legacy receipts with an unknown vendor id: vendor repaired from the ERP PO (the stock movement is kept) | 429 of 429 repaired; 429 found | >= 98% | PASS |
| L5 unparseable legacy quantities: quarantined with a reason | 264 of 264 | >= 99% | PASS |
| X2 count-sheet SKU typos: repaired when a unique single edit exists, never repaired wrongly | 240 of 243 recoverable repaired right (98.8%); wrong repairs 0; unrecoverable ones excluded | recall >= 95%, 0 wrong | PASS |
| X3 cases counted but entered as each: detected against the book (spec recall 85%) | 165 of 175 detected (94.3%); 10 false positives of 23,541 rows | recall >= 85% | PASS |
| X5 counts with the wrong month or year: kept out of the anchors | 75 of 77 | >= 90% | PASS |
| U1/U2 are undetectable by design and are (correctly) used as anchors; the stock flags and residual-error analysis show their cost | U1: 160 rows, 159 used; U2: 31 rows, 31 used | reported | PASS |
| F2 mangled carrier references: matched to the right order/PO (normalisation, then one-edit with date evidence) | 416 of 435 matched right (95.6%); 0 matched wrong; 19 to review | >= 95% right-or-review, 0 wrong | PASS |
| F4 impossible delivery times: dropped and flagged | 64 of 64 | >= 98% | PASS |
| F5 missing weights: imputed from the matched document, within 10% of the true weight | 528 of 575 within 10% (91.8%); 568 imputed | >= 85% | PASS |
| F7 duplicate carrier charge lines: flagged as recoverable dollars | 196 of 196 flagged (100.0%); 0 false flags; recoverable $12,942 | recall >= 90%, 0 false flags | PASS |
| W4 WH-02 bin relabelling: bins normalised to one scheme (checked on putaways after the change) | 2,883 of 2,883 equal the master bin | 100% (apart from the W5 mis-keyed items) | PASS |
| W1 duplicate WMS deliveries: removed (event_id), one row per event | 1,811,717 unique events; 32,567 duplicate copies collapsed | unique event_id | PASS |
| W3 events for items not yet linked: resolved after the link appeared, and marked | 1,950 movements resolved late and flagged | > 0, none dropped | PASS |
| dbt tests (keys, not-null, accepted values, relationships, coverage, evidence on inferences) | PASS=71 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=71 (15s) | ERROR=0 | PASS |
| a full rebuild of every model reproduces identical tables | 53/53 tables identical; rebuild took 77s (PASS=79 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=79) | all identical | PASS |
