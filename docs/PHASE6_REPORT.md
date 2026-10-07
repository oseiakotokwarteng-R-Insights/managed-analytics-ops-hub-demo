# System 1 — Phase 6 Report: The Dashboard

Gates: **ALL PASS** (16/16). Targets: **1 of 2 met**, 1 missed (published as measured).

## What was built

A static, mobile-first site (`dashboard/`): plain HTML, CSS and JavaScript with no build step and no libraries, reading pre-aggregated JSON exported from the marts. Phone layout is the base design (bottom tab bar, one column, 44 px touch targets); wider screens add a top navigation and multi-column cards. Light and dark themes follow the device.

| View | Answers | Content |
|---|---|---|
| Overview | all eight business questions | one card per question, last night's status |
| Stock | Q1, Q3 | search any item, today's position in all six warehouses, history slider for any past date, count accuracy by month, biggest gaps between our estimate and the system |
| Risk and inbound | Q2, Q4 | items that will run out within 14 days or already have, transfer suggestions, open and overdue purchase orders, supplier on-time rates |
| Exceptions | Q6 | phantom-stock alert with its timeline, affected items, review queue by owner and action, what was fixed automatically |
| Freight | Q5 | cost per 100 lb, per order and per unit by carrier, slow-shipment rate, lanes, charge breakdown, recoverable duplicate charges |
| Pipeline health | Q7 | every night of history, alert log, feed freshness, defect-rate charts, row conservation, plain-words check catalog |
| Scorecard | Q8 and the proof | all phase results including misses, modeled manual-hours estimate with assumptions |
| Roadmap | strategy panel | count-frequency finding from this data, maturity path |

## New analytics (all in dbt, tested)

`mart_stock_current`, `mart_stock_risk_daily` (demand, promised inbound, days of cover, run-out risk, transfer suggestions), `mart_inbound_open`, `mart_vendor_ontime`, `mart_count_accuracy`, `mart_ghost_stock_line / daily / episode` (phantom stock), `mart_freight_shipment / weekly / lane`, `mart_manual_effort`. Seeds: `service_standards`, `manual_effort_assumptions`.

## Run-out risk, scored against physical truth

| Rule | Precision | Recall | F1 |
|---|---|---|---|
| Reconstructed stock (dashboard) | 59.1% | 64.7% | 0.618 |
| The systems' own recorded book | 40.3% | 65.5% | 0.499 |

Scored on weekly as-of dates over the last 150 days: did physical stock hit zero within the next 14 days? Thresholds (precision 50%, recall 70%) were set before the backtest ran.

## Phantom stock (scenario S1)

The alert watches for order lines that sit unshipped for more than a week while the book says stock is on hand, per warehouse, against a threshold learned from the first year. It needs no counts. Truth: stock lost at WH-05 on 2026-03-10, found by a count on 2026-05-18.

- Pipeline's estimated start: **2026-03-10** (+0 days). Alert raised **2026-03-18**, 8 days after the loss and **61 days before the count**.
- 60 items named, 98% truly affected, 69% of all affected items found; 436 stuck order lines worth $70,410; book value at risk $69,274 vs $85,424 truly lost.
- No alert at any other warehouse on any night.

## Honest notes

- **The start-date estimator was revised once.** The first version took the earliest stuck order in the cluster and started the episode a month early (stray late orders, plus never-closed order lines that age forever). The final version counts a SKU's start only when a stuck line is followed by another, takes the third earliest SKU, and ages dead lines out after 60 days. It was designed on the mechanism, not fitted to the truth date, but the first result was seen before the redesign.

- **A thing I tried and dropped:** a chart of how the system book's accuracy changes with time since the previous count. In this data the book is wrong about 20% of the time at every interval, so it told no story. The count-frequency finding on the roadmap uses the accuracy of the *reconstructed estimate* by time since last count (Phase 4, scored against truth) instead.

- **Freight cost windows end three days before the data does.** Carriers invoice on delivery, so the newest shipments have no charges yet and would make every cost figure look too low.

- **'Slow' shipments are judged against assumed standards** (the feeds carry no promised delivery dates); the assumptions are published on the dashboard.

- **Modeled, not measured:** the manual-hours figure multiplies real counts by assumed minutes per item. It is labelled MODELED wherever it appears.

- **Browser checks** (phone, tablet-width desktop, dark mode) were done by hand in a real browser pane; they are not part of this automated gate.


## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| every data file and one history file per item exist | 11 of 11 data files; 2,800 of 2,800 item histories | all | PASS |
| the item histories on the dashboard equal the stock mart (any item, any date) | 1800 of 1800 sampled item-warehouse-days identical (estimate, system figure, confidence) | all identical | PASS |
| overview figures equal the marts they summarise | 12,708 pairs, 180 at risk, 137 out, 1,262,439 units to promise | identical to the mart | PASS |
| the scorecard shows every phase result, misses included | phases [1, 2, 3, 4, 5, 6, 7, 8]; failed checks 0; missed targets shown: 5 | phases 1-5 present | PASS |
| the manual-effort figure is labelled as a modeled estimate with its assumptions | modeled=True, 14 rows each with minutes per item and basis | labelled | PASS |
| the slow-shipment definition is published with its assumptions | outbound > 4 days; inbound > 6 days | stated | PASS |
| the first screen loads in under 100 KB over the wire (data and code, compressed) | data 23 KB gz, code 83 KB raw (about 21 KB gz); item search index 188 KB gz loaded on first search; one item history about 0.8 KB gz | data+code <= 100 KB gz | PASS |
| published data volume | 40.9 MB over 2,811 files (compresses to about 2.6 MB) | reported | INFO |
| nothing from the answer key is published (no table names, no non-JSON files) | 0 files mention an answer-key table; 0 non-JSON files | 0 and 0 | PASS |
| all dashboard code parses and the overview answers all 8 business questions | 11 files, 0 with errors; 8 question cards | 0 errors, 8 cards | PASS |
| backtest sample | 141,112 item-warehouse-days with demand, on 20 weekly as-of dates, scored on whether physical stock hit zero within the next 14 days (base rate 4.6%) | reported | INFO |
| SPEC-style target: the risk list catches at least 70% of real run-outs at 50%+ precision | recall 64.7%, precision 59.1% (4,156 true, 2,873 false alarms, 2,271 missed) | recall >= 70% and precision >= 50% | MISSED |
| the reconstructed stock beats the systems' own book at predicting run-outs (F1) | ours F1 0.618 (precision 59.1%, recall 64.7%) vs recorded book 0.499 (precision 40.3%, recall 65.5%) | ours > book | PASS |
| hit rate by risk class | at_risk: 34.9% ran out (3,756); ok: 1.7% ran out (134,083); out_of_stock: 87.0% ran out (3,273) | reported | INFO |
| exactly one phantom-stock episode is reported, at the right warehouse | 1 episode(s): WH-05; truth: WH-05 | 1 at the scenario warehouse | PASS |
| no alert at any other warehouse on any night of the 730 (false alarms) | 0 alert nights elsewhere | 0 | PASS |
| SPEC target (S1): the history shows when the loss began, within 3 days of the truth | estimated 2026-03-10 vs true 2026-03-10 (+0 days) | within 3 days | MET |
| alert latency | alert raised 2026-03-18, 8 days after the loss began and 61 days before the count that discovered it (2026-05-18) | reported | INFO |
| the first confirming count the pipeline finds is the count that discovered the loss | pipeline: 2026-05-18; truth discovery: 2026-05-18 | same date | PASS |
| items named as affected are really affected (precision) | 59 of 60 named items are among the 85 that lost stock = 98.3% | >= 95% | PASS |
| share of the affected items found (recall) | 59 of 85 = 69.4%; the rest had fewer than three orders in the window, so no pattern to see | reported | INFO |
| the book value flagged at risk is close to the true value lost | flagged 69,274 vs truly lost 85,424 (ratio 0.81) | within 25% | PASS |
| the latest dbt test run, including the new mart tests, passes | 69 of 69 tests pass | all pass, at least 60 recorded | PASS |
