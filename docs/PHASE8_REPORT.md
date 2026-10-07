# System 1 — Phase 8 Report: The Validation Scorecard

Gates: **ALL PASS** (9/9). Scorecard: **6 of 8 success criteria met**, **31 of 32 defect classes at their catalog target**, **4 of 5 scenarios met**. Every miss is listed below and on the dashboard.

## How to read this

The source data is synthetic, so the right answer is known for every row. This scorecard compares what the pipeline did against that answer key, using targets that were written down before anything was built (`SPEC.md` section 8 and `DEFECT_CATALOG.md`; target text fingerprint `1b47b3af5d4a`). Targets are read from those documents by the code, and a gate checks that every target on the scorecard equals the document's.

A defect is scored only if its record had been delivered by the end of history, and a class counts as handled only if the pipeline did what the catalog says it should: fixed it correctly, quarantined it, flagged it, or sent it to a person. Wrong repairs are counted and shown beside the rate; the pass mark is the catalog's target for the rate.

## The eight success criteria (SPEC section 8)

| Measure | Target | Measured | Result |
|---|---|---|---|
| SKU crosswalk precision / recall (auto-matched) | ≥ 99.5% / ≥ 97%; remainder goes to `review_queue`, none silently wrong | precision 99.97% on 2,919 automatically resolved shared-code rows; recall 99.47% of 80,754 legacy rows resolved, the rest sent to review | MET |
| Defect detection recall for classes marked detectable | ≥ 95% per class | 30 of 32 detectable classes at 95% or better; below: E1 89.3%, X3 94.3% | MISSED |
| Quarantine false-positive rate (good rows wrongly rejected) | ≤ 1% | 0 good rows rejected of 711,946 good rows = 0.0000% (2,486 rows quarantined, 2,486 of them truly defective) | MET |
| Reconstructed on-hand vs true on-hand, SKU×warehouse×day (excluding unresolved items) | ≥ 98% exact match | 97.90% exact on the 92.0% of 9,276,840 pair-days not flagged suspect (95.13% on all days; the systems' own book 87.40%) | MISSED |
| Idempotency: re-running any load | zero diff | 12 ingestion tests pass, including: a re-run changes no table in any way, a crash mid-load leaves nothing half-written, a changed file is versioned not duplicated, a late or corrupt file is handled; a repeated live tick also changes nothing (Phase 7) | MET |
| Backfill after the WMS outage scenario self-heals the stock history | yes, verified against truth | first alert 0 days after the outage began; after the catch-up the stock estimate is exact on 94.17% of Flagstaff pair-days over the outage and the following week (the two weeks before: 94.43%); replayed as of 2026-01-22, with only what had arrived by then: 100% of that warehouse's stock estimates on 2026-01-22 were marked suspect (feed silent), 0 estimates flagged on other warehouses | MET |
| Schema-drift scenario detected, not silently failed | detected same run; mapped or paused with an alert | first ERROR 2026-06-04 (4 files held, then released after the layout was approved); weights of shipments around the change equal the truth on 160 of 160 | MET |
| Daily live run completes and mart exports refresh | ≤ 30 min | slowest run 7.7 min (104-day catch-up); one-day runs: 3, median 2.5 min, slowest 2.7 min | MET |

## The five headline scenarios

| ID | Scenario | Target | Measured | Result |
|---|---|---|---|---|
| S1 | Phantom stock, Albuquerque | start date within 3 days | start estimated 2026-03-10 (+0 days); alert raised 2026-03-18, 61 days before the count that found it; 59 of 60 named items truly affected; 436 stuck order lines ($70,410); 0 false alarms elsewhere | MET |
| S2 | Carrier B changes its file layout | detected the same night, no wrong cost | first ERROR 2026-06-04 (4 files held, then released after the layout was approved); weights of shipments around the change equal the truth on 160 of 160 | MET |
| S3 | Flagstaff warehouse feed goes quiet, then bursts in late | alert within 2 days; healed history within 1 point of normal; gap marked while open | first alert 0 days after the outage began; after the catch-up the stock estimate is exact on 94.17% of Flagstaff pair-days over the outage and the following week (the two weeks before: 94.43%); replayed as of 2026-01-22, with only what had arrived by then: 100% of that warehouse's stock estimates on 2026-01-22 were marked suspect (feed silent), 0 estimates flagged on other warehouses | MET |
| S4 | Carrier A double-bills about 1% of shipments | 90% of duplicate lines flagged, none falsely | 196 of 196 duplicate lines in the delivered files flagged ($12,942 recoverable against $12,991 truly duplicated in the delivered files); 0 false flags | MET |
| S5 | Roofing demand surge, Las Vegas | recall >= 70% and precision >= 50% on the surge items (the bars used for the run-out list) | on the 30 surge items, weekly as-of dates in the surge: the list caught 41 of 61 real run-outs (67% recall, 100% precision); the systems' own book: 72% recall, 96% precision; a transfer source with spare stock existed for 38 of 41 caught run-outs | MISSED |

## Every detectable defect class (32)

| ID | Defect | Scored | Handled right | Catalog target | Result | Wrong repairs | What was measured |
|---|---|---|---|---|---|---|---|
| E1 | Superseded item still on orders | 4,901 | 89.33% | 98.0% (recall) | MISSED |  | 4,378 re-pointed to the right item, none to a wrong one; the other 523 stay as keyed, 518 of them Albuquerque orders, where no warehouse-system evidence exists to name the successor |
| E2 | Re-keyed duplicate order lines | 3,734 | 99.44% | 95.0% (recall) | MET |  | 3,171 exact duplicates dropped, 542 near-matches flagged for a person; 0 real lines wrongly dropped |
| E3 | Zero or negative quantity | 908 | 100.00% | 99.0% (recall) | MET |  |  |
| E4 | Ship-from warehouse missing or invalid | 1,807 | 100.00% | 95.0% (recall) | MET |  | 1,773 filled correctly, 34 with neither a default nor a sibling line left for a person; 0 wrong fills |
| E5 | Quantity entered in cases | 9,218 | 100.00% | 99.0% (recall) | MET |  |  |
| E5b | Cases with no case size | 582 | 99.31% | 98.0% (recall) | MET |  | scored on order lines (the item-master rows that cause it are the same defect seen from the other side) |
| E6 | Quantity changed after shipment | 4,146 | 100.00% | 95.0% (recall) | MET |  |  |
| W1 | Duplicate warehouse events | 32,567 | 100.00% | 99.5% (recall) | MET |  | duplicate deliveries that arrived: 32,567; each is one row in the stock ledger |
| W2 | Late and out-of-order warehouse events | 15,627 | 100.00% | 99.0% (recall) | MET |  | late events that move stock, placed on the day they happened rather than the day they arrived |
| W3 | Events for items not yet linked | 1,987 | 100.00% | 95.0% (recall) | MET |  | stock-moving events for not-yet-linked items, all in the ledger under the right item; 1,950 carry the 'linked late' mark |
| W4 | Bin label format change | 2,883 | 100.00% | 100.0% (recall) | MET |  | scored on putaways in Tucson after the label change: the bin on the dashboard equals the bin in the item's master record |
| W5 | Receipt keyed under the wrong item | 517 | 98.84% | 90.0% (recall) | MET | 1 | 511 re-assigned to the right item from the PO, 2 sent to review, 0 receipts wrongly touched |
| W6 | Ship confirmation never arrives | 2,659 | 99.96% | 90.0% (recall) | MET |  | shipments reconstructed from pick, pack and the ERP; 95 further inferences are shipments still unconfirmed at the end of history |
| F1 | Carrier re-sends a whole file | 3 | 100.00% | 100.0% (recall) | MET |  | each re-sent file raised a duplicate-file alert the night it arrived |
| F2 | Mangled order or PO reference | 435 | 100.00% | 95.0% (recall) | MET |  | 416 matched to the right order or PO, 19 sent to review, 0 matched wrong |
| F4 | Impossible delivery time | 64 | 100.00% | 98.0% (recall) | MET |  |  |
| F5 | Weight or piece count missing | 854 | 100.00% | 100.0% (recall) | MET |  | every missing weight or piece count is marked; of 575 missing weights, 568 imputed from the matched document and 528 of those within 10% of the true weight |
| F7 | Duplicate carrier charge line | 196 | 100.00% | 90.0% (recall) | MET |  | 0 false flags |
| L1 | Legacy item codes need a crosswalk | 2,919 | 99.97% | 99.5% (precision) | MET | 1 | of 3,347 rows with a shared legacy code, 2,919 were resolved automatically and 428 left to review; precision is measured on the resolved ones |
| L2 | Legacy dates in mixed formats | 142 | 100.00% | 99.0% (recall) | MET |  |  |
| L4 | Receipt with an unknown vendor | 429 | 100.00% | 98.0% (recall) | MET |  |  |
| L5 | Legacy quantities stored as text | 264 | 100.00% | 99.0% (recall) | MET |  |  |
| L6 | Duplicate vendor records | 7 | 100.00% | 100.0% (recall) | MET |  | 5 of 5 strong matches merged automatically, 2 of 2 weak matches sent to review |
| X1 | Count-sheet headers differ | 31 | 100.00% | 100.0% (recall) | MET |  | files whose column headers differ from the usual; scored on whether every row arrived |
| X2 | SKU typos on count sheets | 438 | 99.32% | 95.0% (recall) | MET |  | 240 of 243 recoverable typos repaired, 195 of 195 unrecoverable ones excluded for a person; 0 wrong repairs |
| X3 | Cases counted but entered as each | 175 | 94.29% | 85.0% (recall) | MET |  | 10 good rows also flagged, of 23,541 |
| X4 | Merged cells, subtotals, blank rows | 138 | 100.00% | 100.0% (recall) | MET |  | every sheet with merged cells, subtotals and blank rows delivers exactly its real rows |
| X5 | Count dated the wrong month | 77 | 97.40% | 90.0% (recall) | MET |  | kept out of the stock anchors |
| X6 | Conflicting vendor price overrides | 86 | 100.00% | 95.0% (recall) | MET |  | each conflicting price is in a flagged pair with a documented rule (the later entry is used until a person confirms) |
| C1 | ERP receipt differs from warehouse receipt | 631 | 100.00% | 95.0% (recall) | MET |  |  |
| C2 | Order shipped in ERP, no ship event | 2,659 | 99.96% | 90.0% (recall) | MET |  | same cases as W6, scored against the C2 target: the shipment is reconstructed from pick, pack and the ERP, with carrier evidence where it exists |
| C3 | One-sided transfer | 144 | 100.00% | 95.0% (recall) | MET |  | missing out-side inferred for 69 of 69; missing in-side listed as in-transit for 75 of 75 |

## Known misses: defects that pass through by design

The pipeline cannot see these, and says so. Each has a recommended control that is a business process, not a pipeline fix.

| ID | What | Rows | Recommended control |
|---|---|---|---|
| U1 | Counts from one manager biased about +2% for three months | 160 | Blind double counts on a sample, or comparing each counter's variances with the others'. Each row looks plausible alone. |
| U2 | Two valid SKUs swapped on a count sheet | 31 | Scan or barcode capture at the bin instead of typed codes. |
| U3 | Theft or damage that nothing records | 1,755 | More frequent counts on fast movers and flagged items; no pipeline can see a cause nobody wrote down. |

## Honest notes

- **Two readings of 'detection recall'.** The spec asks for 95% on every class; the catalog sets a target per class (some lower, such as 85% for cases-counted-as-each). Both are shown. Against the spec's flat bar, the classes that miss are listed in criterion 2; against the catalog's own targets the misses are the rows marked MISSED in the class table.

- **Two gaps were closed while building this scorecard, and one was not.** Scoring every class showed that price-override conflicts (X6) were staged but never flagged, and that missing piece counts (F5) were not marked, so both were built (a conflict list that goes to purchasing, and an explicit missing-pieces flag) before being scored. The stock table also now marks a warehouse's estimates as suspect while its feed is silent, which the outage scenario required and a point-in-time replay verifies. The Albuquerque item re-keys (E1) are not fixable with the evidence available and remain a miss.

- **The stock-accuracy target is missed, and the live months are lower still.** See criterion 4 and Phase 7: unrecorded shrink accumulates between counts, so the lever is how often items are counted.

- **The 'manual hours replaced' figure is a modeled estimate**, not a measurement, and is labelled that way on the dashboard.

- **Numbers here are as of the end of history (2026-09-30).** The live clock leaves them untouched; the live period has its own results in the Phase 7 report.


## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| the eight criteria and their targets on the scorecard are exactly SPEC section 8 | 8 criteria; targets equal the document's: True | identical | PASS |
| every class target on the scorecard is the catalog's | 32 classes; 32 equal the catalog's target | all equal | PASS |
| every defect class in the answer key is on the scorecard, as a scored class, a known miss or a scenario | 36 codes in the log; not accounted for: none | none missing | PASS |
| no scored class is empty (every class had defects to find in the delivered data) | smallest class F1 with 3 instances | >= 3 each | PASS |
| the on-hand figure equals the Phase 4 report's | scorecard 97.90% exact on the 92.0% of 9,276,840 pair-days...; Phase 4: 97.90% exact on the 92.0% of pair-days not flagged suspect | same percentage | PASS |
| class results equal the Phase 4 handling checks they came from (W5 and F7 counts) | W5: scorecard 511 of 517, Phase 4 '511 of 517 corrected right (98.8% re' | same counts | PASS |
| F7 recoverable-dollar count equals Phase 4's | scorecard 196 of 196; Phase 4: 196 of 196 flagged (100.0%); 0 false fla | same counts | PASS |
| everything that missed, in one place | classes ['E1']; scenarios ['S5']; criteria [2, 4] | reported | INFO |
| scoring is deterministic: a second run gives identical results | identical | identical | PASS |
| the published scorecard contains scores only: no answer-key table names | none found | none | PASS |
