# System 1 — Defect Catalog (Phase 0)

Status: DRAFT for approval. Companion to `SPEC.md`.

Every defect below is injected by the generators, logged in `truth_defects` with its ID, and later scored in the validation scorecard. Rates are of the stated base population and are my best estimate of what a real mid-size distributor's systems look like; they are tunable before Phase 2 starts.

**Handling classes:** AUTO-FIX · DEDUPE · QUARANTINE · FLAG · REVIEW · UNDETECTABLE (see SPEC §6).
**Detection target** means the minimum share of injected instances the pipeline must correctly handle as described.

## 1. How to read this

`ID` is stable (E = ERP, W = WMS, F = Freight, L = Legacy, X = Spreadsheets, C = cross-source, S = scenario, U = undetectable). The *Expected handling* column is the behavior the pipeline is built to achieve, not a guarantee; the scorecard reports what it actually achieved.

## 2. Defects by source

### ERP (base: ~612k order lines, ~180k orders, item master)

| ID | Defect | Rate | Expected handling | Target |
|---|---|---|---|---|
| E1 | Superseded SKU still on open orders (successor exists in item master) | 0.8% of lines | AUTO-FIX via supersession map, change logged | 98% |
| E2 | Duplicate order lines from re-keyed orders. 70% sit inside the same order, 15% arrive as a new order 2-9 minutes later (exact), 15% as a new order 11-25 minutes later (near-match). Duplicates stay open with nothing shipped | 0.6% of lines | DEDUPE the exact cases; FLAG the near-matches (cannot be proven duplicates) | 95% |
| E3 | Zero or negative quantity on a non-return line | 0.15% of lines | QUARANTINE | 99% |
| E4 | Ship-from warehouse null or invalid code (the ERP header carries no warehouse; 20% of customer accounts have a blank default warehouse) | 0.3% of lines | AUTO-FIX from the customer's default warehouse, or from a sibling line on the same order; QUARANTINE only when neither exists | 95% |
| E5 | Non-base UOM (CS vs EA) correctly converted | 1.5% of lines | AUTO-convert (legitimate, not an error) | 99% |
| E5b | Non-base UOM with missing/stale conversion factor | 0.1% of lines | QUARANTINE | 98% |
| E6 | Order quantity changed after shipment posted (late modification) | 0.7% of lines | AUTO, effective-dated versions retained | 95% |

### WMS (base: ~1.8M events, 5 warehouses)

| ID | Defect | Rate | Expected handling | Target |
|---|---|---|---|---|
| W1 | Duplicate events (at-least-once delivery) | 1.8% of events | DEDUPE on `event_id` | 99.5% |
| W2 | Late / out-of-order events (arrive up to 72 h after event time) | 2.5% of events | AUTO via event-time ordering and late-arrival window | 99% |
| W3 | WMS events for an item the ERP item master does not yet link to a WMS item id (new items are linked 0-35 days after first receipt) | ~0.25% of events (natural result of the link lag; 4,364 in the build) | QUARANTINE, auto-released when the link appears | 95% |
| W4 | Bin code format drift: WH-02 changes from `A-12-3` to `A12-03` on 2026-02-15 | 100% of WH-02 events after cutover | AUTO via versioned mapping | 100% |
| W5 | A receipt is keyed under the wrong item (another SKU in the same category and warehouse). The true item's book is short, so later picks exceed on-hand and drive it negative | 0.8% of RECEIVE events (the cause, 517 in the build); the negative-stock picks are the symptom | AUTO-FIX by comparing the receipt's item with the items on the ERP PO it references; negative-stock episodes are also flagged | 90% of receipts |
| W6 | Pick and pack present, ship confirmation missing | 0.5% of order lines | FLAG; resolved by freight evidence where possible (see C2) | 90% |

### Freight (base, from the Phase 1 truth data: ~18.2k Carrier A shipments with ~39.9k charge lines, ~10.0k Carrier B shipments)

The simulated business moves most deliveries on its own fleet or will-call (~185k of ~241k shipment records), so only ~28k shipments ever appear in a carrier feed. Rates below are unchanged; counts are correspondingly smaller (F2 ≈ 420, F4 ≈ 56, F5 ≈ 850).

| ID | Defect | Rate | Expected handling | Target |
|---|---|---|---|---|
| F1 | Carrier re-sends a full prior-day file | 3 occurrences | DEDUPE on shipment + event key | 100% |
| F2 | Order/PO reference mangled (leading zeros stripped, typos, wrong case) | 1.5% of shipments | AUTO via key normalization; remainder to REVIEW | 95% |
| F4 | Delivery timestamp earlier than ship timestamp, or impossible transit time | 0.2% of shipments | QUARANTINE | 98% |
| F5 | Weight or piece count missing | 3% of shipments | FLAG; cost allocation uses imputed value, marked as imputed | 100% |
| F7 | Carrier A bills a duplicate of an existing charge line (fuel surcharge or accessorial; 10% of cases duplicate the linehaul) | 1.0% of Carrier A shipments (~180 shipments, roughly $15k recoverable) | FLAG for dispute, surfaced as "recoverable dollars" | 90% |

(F3 is the Carrier B schema change; see scenario S2. F6, fuel surcharge shown as a separate line vs embedded, is structural and handled in modeling, not a defect.)

### Legacy DB (base: ~90k inventory transactions, vendor and cost tables, all WH-05 movements)

| ID | Defect | Rate | Expected handling | Target |
|---|---|---|---|---|
| L1 | Padded/legacy 8-char item codes need crosswalk; some map 1-to-many after product-line merges | 100% of rows need crosswalk; ~6% ambiguous | AUTO where unique, REVIEW where ambiguous, never guessed | precision ≥ 99.5% |
| L2 | Dates stored as text in two terminal-dependent formats (`MM/DD/YY` for terminal T1, `DD-Mon-YYYY` for T2). Rows with a blank terminal id may be `MM/DD/YY` or `DD/MM/YY` | 100% parse via the terminal rule; 0.5% of rows have a blank terminal, of which the day-ambiguous ones (day <= 12, day != month) are ~0.17% of rows | AUTO with per-field documented rule; ambiguous cases FLAG | 99% |
| L4 | Receipt rows whose vendor ID is absent from the vendor master (only receipts carry a vendor) | 5% of receipt rows (~0.5% of all transactions) | The stock movement is kept (it is valid); the vendor is repaired from the ERP PO the receipt references | 98% |
| L5 | Numerics stored as text with symbols/commas; some unparseable | 100% parse; 0.3% unparseable | AUTO, unparseable QUARANTINE | 99% |
| L6 | Duplicate vendor records (same supplier under two IDs) | 7 pairs of ~140 vendors | AUTO-merge on strong match, REVIEW on weak | 100% strong / flagged weak |

(L3 is the phantom stock at WH-05; see scenario S1.)

### Spreadsheets (base: ~25k count rows, ~6k price-override rows)

| ID | Defect | Rate | Expected handling | Target |
|---|---|---|---|---|
| X1 | Header names differ by branch and month ("On Hand", "OH", "Qty Counted") | ~35% of files targeted; 24% realised (34 of 144, sampling variation on a small file count) | AUTO-map headers | 100% |
| X2 | SKU typos (transposed digits, O vs 0) | 2.0% of count rows | AUTO-FIX if a single edit yields exactly one valid SKU, else REVIEW | 95% |
| X3 | UOM mistake (cases counted but entered as each) | 0.8% of count rows | FLAG via count-vs-system plausibility check | 85% |
| X4 | Merged cells, subtotal rows, blank rows, notes in data area | 100% of files | AUTO-strip, row counts reconciled to sheet | 100% |
| X5 | Count dated wrong month or year | 0.4% of count rows | FLAG | 90% |
| X6 | Conflicting vendor price overrides (two prices for same SKU/vendor/date) | 1.5% of price rows | FLAG, documented latest-wins rule applied | 95% |

## 3. Cross-source defects

| ID | Defect | Rate | Expected handling | Target |
|---|---|---|---|---|
| C1 | ERP receipt quantity differs from what the WMS received: keying errors (x10, /10, digit slips) and short shipments recorded as full | 1.9% of POs (631 PO lines) | FLAG into variance queue | 95% |
| C2 | ERP shows order shipped, WMS ship event absent, carrier shows delivered | 0.5% of order lines | AUTO-reconcile with an evidence score; low-score cases REVIEW | 90% |
| C3 | Inter-warehouse transfer recorded one-sided (out without in, or the reverse) | 1.2% of transfers | FLAG, shown as in-transit inventory until resolved | 95% |

## 4. Headline scenarios (the demo walkthrough stories)

Each is a dated, deliberate incident with a known truth, built to be found live.

| ID | Date(s) | What happens | What the system must show |
|---|---|---|---|
| **S1 Phantom stock, Albuquerque** | Begins 2026-03-10; discovered by a count 2026-05-18 | For 85 SKUs at WH-05, legacy adjustments stop posting. System shows stock; true stock is zero. Orders are accepted and later backordered. | Count variance and negative-pick signals raise a "phantom stock" alert; dollars at risk and affected orders quantified; the history shows *when* it started, matching truth within ±3 days |
| **S2 Carrier B schema change** | 2026-06-04 | `weight_lb` becomes `wt_lbs`, `service` splits into two fields, a `dim_weight` column appears. | Drift detected in the same run it appears; mapped via contract versioning or paused with an alert. Never a silent failure and never silently wrong cost |
| **S3 WMS outage, Flagstaff** | 2026-01-21 → 2026-01-23 (48 h) | No WH-03 events for two days, then a burst arrives 36–60 h late, out of order. | Mart marks the gap honestly while it exists; stock history self-heals after backfill and matches truth |
| **S4 Double-billed freight** | Spread across 24 months | Carrier A bills a duplicate charge line on ~1% of its shipments (~180 shipments, roughly $15k). | "Recoverable dollars" view with the specific charge lines |
| **S5 Roofing demand surge, Las Vegas** | June–July 2026 | Demand for ~30 roofing/underlayment SKUs runs ~2.4× normal at WH-04. | Stockout-risk view flags them with days-of-cover and suggests transfer sources with available stock |

## 5. Defects that deliberately pass through (honesty section)

Real systems have problems pipelines cannot see. Including some makes the scorecard credible, and showing them is part of the pitch ("here is what this cannot catch, and here is what would catch it").

| ID | Defect | Rate | Handling | Why it escapes |
|---|---|---|---|---|
| U1 | One branch manager's counts (Tucson, Feb-Apr 2026) are systematically biased about +2% | 1 manager, 3 months, 160 count rows | UNDETECTABLE per row; only detectable statistically across managers | Each row is individually plausible |
| U2 | Two *valid* SKUs transposed in a count sheet (both exist, similar descriptions) | 0.1% of count rows | UNDETECTABLE at ingestion; may surface as a later count variance | Passes every format and existence check |
| U3 | Real shrink (theft/damage) indistinguishable from miscount | ~0.3% of stock value/yr | UNDETECTABLE as a cause; visible only as unexplained variance | No source records the cause |

The scorecard reports U1–U3 as known misses, with the recommended control for each (for example, blind double counts, which is a Data Strategy recommendation, not a pipeline fix).

## 6. Injected-defect volume (actuals from the Phase 2 build)

The defect log (`truth/truth_defects.parquet`) holds 120,776 entries across the five sources. They fall into four kinds:

| Kind | Entries | Notes |
|---|---|---|
| Mechanical delivery effects | ~77,700 | W1 duplicates (32.6k) and W2 late arrivals (45.1k); handled by standard idempotency and event-time logic |
| Legitimate but must be handled | ~16,700 | E5 case-quantity lines (9.2k), E6 post-shipment quantity changes (4.1k), L1 legacy codes shared by several SKUs (3.4k rows) |
| Genuine data-quality defects | ~21,700 | ERP E1-E4, E5b (11.9k); WMS W3, W5, W6 (7.6k); freight F1-F7 (1.6k); legacy L2, L4-L6 (0.8k); spreadsheets X2, X3, X5, X6 and C1/C3 cross-source (1.5k) |
| Scenarios, file-level and undetectable | ~4,700 | S2, S3 (652 events), W4 and X1/X4 file-level entries, U1 (160), U2 (31), U3 (1,755 unrecorded shrink events) |

The business-meaningful defects (phantom stock, count variances, double billing, mismatched receipts, dropped ship confirmations) number in the low thousands. Counts per class are large enough for the scorecard to produce meaningful rates, except the deliberately tiny classes (F1, L6, the scenarios), which are scored as pass/fail.
