# System 1 — Unified Operations Hub: Specification (Phase 0)

Status: DRAFT for approval. No code written yet.
Companion file: `DEFECT_CATALOG.md` (every flaw injected into the data, with rates and expected handling).

## 1. Purpose

A working demonstration of Managed Analytics' Data Engineering + Analytics/BI capability. A prospect should see five disconnected, messy systems become one trustworthy view of inventory, and be able to verify the system is honest about what it catches and what it misses.

- **Audience:** owners/operators and ops/finance leads at distributors, wholesalers, and multi-site operators (SMB to mid-market).
- **Takeaway:** "He can take our scattered systems and make them agree, and he shows his work."
- **Non-goals:** no ML forecasting (that is System 3), no causal analysis (System 2), no real client data, no real company or person names.
- **Labeling:** everything is visibly marked synthetic in the UI and docs, consistent with the site's illustrative case studies.

## 2. The fictional company (placeholder name: "Northfield Supply Co.")

| Attribute | Value |
|---|---|
| Business | Regional building-supply distributor, Southwest US |
| Size | ~120 employees, ~$48M annual revenue (synthetic) |
| Warehouses | 6: WH-01 Phoenix (hub, ~30% of volume), WH-02 Tucson, WH-03 Flagstaff, WH-04 Las Vegas, WH-05 Albuquerque (acquired, still on the legacy system), WH-06 El Paso |
| Catalog | ~2,500 active SKUs in 12 categories, plus ~300 discontinued/superseded |
| Customers | ~1,600 active accounts (≈60% contractors, 25% retail, 15% municipal/commercial) |
| Suppliers | ~140 vendors |
| Orders | ~7,500/month, ~3.4 lines each |
| History | 2024-10-01 → 2026-09-30 (24 months), then a live clock advancing one simulated day per real day |

Time zones are deliberately mixed (Arizona has no DST; Las Vegas, Albuquerque, El Paso do). That is a real-world trap, not an accident.

## 3. The hidden truth (the answer key)

One internally consistent simulated business is generated first: demand (seasonality by category, trend, promotions), purchasing and replenishment, receipts, inter-warehouse transfers, and shipments. From it we record the **true on-hand quantity for every SKU × warehouse × day**, plus true SKU identity, true vendor identity, and true shipment linkage.

Each source system is then *derived* from the truth and corrupted per the defect catalog. The truth is kept in a separate `truth/` store that the pipeline never reads. It is used only by the validation scorecard (Phase 8).

Every injected defect is logged with an ID in a `truth_defects` table (source, row, class, defect ID), so detection can be scored exactly.

## 4. Source systems (the five)

| # | System | Format / delivery | Grain | Cadence | Identifiers | What it uniquely contributes |
|---|---|---|---|---|---|---|
| 1 | **ERP** | Relational extracts (CSV/Parquet) | order line, PO line, invoice, item master | Nightly full + incremental | `NF-10234-A` style SKU, order no., PO no. | Orders, purchasing, prices, customers, item master |
| 2 | **WMS** | JSON event stream per warehouse | one stock movement event | Hourly batches (at-least-once) | numeric `item_id`, bin code, `event_id` | Physical movements: receive, putaway, pick, pack, ship, adjust, transfer, count. Covers WH-01–04 and WH-06 |
| 3 | **Freight (2 feeds)** | Carrier A (LTL): JSON with nested tracking events. Carrier B (parcel): daily CSV | shipment / tracking event / charge | Daily | BOL no., tracking no., PO or order reference | Transit status, ETA vs promise, freight cost, accessorials |
| 4 | **Legacy DB** | Old Access-style export (SQLite/CSV, text-typed columns) | inventory transaction, vendor, cost | Weekly dump | 8-char padded legacy item codes | **All WH-05 (Albuquerque) inventory movements**, historical vendor costs |
| 5 | **Spreadsheets** | `.xlsx`, human-edited | cycle-count row, price-override row | Monthly drop per branch | free-text descriptions, hand-typed SKUs | Physical cycle counts (the independent check on system stock), vendor price overrides |

**Structural quirks (not defects, but each must be handled):** ERP timestamps are naive local time per warehouse; WMS is UTC ISO-8601; Carrier A is epoch milliseconds; Carrier B is local time with a text offset; Legacy is date-only text in mixed formats; spreadsheets are free-text dates. Units of measure vary (EA vs CS). Identifiers differ across all five systems and are never a clean join key.

## 5. Business questions the finished system must answer

1. How many units of this SKU can I promise today, across all six warehouses, and as of any past date?
2. Which SKUs are at risk of stocking out in the next 14 days, and where could we transfer from?
3. How accurate are our inventory records? (system on-hand vs counted, by warehouse)
4. What is inbound, where is it, and is it late versus the supplier's promise?
5. What does freight cost per unit and per order, by carrier and lane, and what is the late rate?
6. How many orders were backordered or oversold because the records were wrong?
7. Can I trust today's numbers? (freshness, completeness, quarantine counts per source)
8. How much manual reconciliation does this replace? (**modeled estimate**, see §8)

## 6. Build layers

`raw` (as-received, immutable, audited) → `staging` (typed, normalized) → `core` (conformed dimensions: SKU crosswalk, location, vendor; facts: inventory movement, order line, shipment, count) → `marts` (answers to §5). Side tables: `quarantine` (rejected rows with a reason code), `review_queue` (ambiguous matches needing a human), `load_audit`.

Handling classes used throughout: **AUTO-FIX** (corrected, change logged), **DEDUPE**, **QUARANTINE** (excluded, reason recorded), **FLAG** (kept, marked suspect, surfaced), **REVIEW** (routed to a human queue), **UNDETECTABLE** (known to pass through; reported honestly).

## 7. Stack and repository layout

- **Generators:** Python (numpy/pandas; seeded and deterministic, including the per-day live generator).
- **Warehouse:** DuckDB (file-based, free, portable).
- **Modeling and tests:** dbt-core (SQL models, tests, lineage docs) — see risk R1.
- **Orchestration:** lightweight scheduler (decision in Phase 1; default is a plain Python runner invoked by a GitHub Actions cron).
- **Front end:** static, mobile-first dashboard reading pre-aggregated mart exports (JSON/Parquet), deployed to a Cloudflare subdomain. Only marts and the scorecard are published; raw data and the answer key are not.

```
system-1-ops-hub/
  docs/         SPEC, DEFECT_CATALOG, later ARCHITECTURE, data dictionary, runbook
  generator/    universe, source builders, defect injectors
  truth/        answer key (never read by the pipeline)
  sources/      generated native-format source files
  pipeline/     ingestion + dbt project
  dashboard/    static front end
  scorecard/    validation against truth
  tests/
```

Estimated volume: ~2.5–3M rows total (ERP ≈ 0.8M, WMS ≈ 1.8M, freight ≈ 0.1M including tracking events (about 28k carrier shipments), legacy ≈ 0.1M, spreadsheets ≈ 0.03M). The DuckDB file should land in the low hundreds of MB; the published mart exports are far smaller.

## 8. Success criteria (set now, before building, so results aren't tuned to fit)

These are targets. The scorecard publishes **actual** results even when they miss; the misses are part of the demo.

| Measure | Target |
|---|---|
| SKU crosswalk precision / recall (auto-matched) | ≥ 99.5% / ≥ 97%; remainder goes to `review_queue`, none silently wrong |
| Defect detection recall for classes marked detectable | ≥ 95% per class |
| Quarantine false-positive rate (good rows wrongly rejected) | ≤ 1% |
| Reconstructed on-hand vs true on-hand, SKU×warehouse×day (excluding unresolved items) | ≥ 98% exact match |
| Idempotency: re-running any load | zero diff |
| Backfill after the WMS outage scenario self-heals the stock history | yes, verified against truth |
| Schema-drift scenario detected, not silently failed | detected same run; mapped or paused with an alert |
| Daily live run completes and mart exports refresh | ≤ 30 min |

**Integrity note on question 8:** the "manual hours replaced" figure is a *modeled* estimate (rows needing manual matching × assumed minutes per match, assumptions shown), not a measured result. It will be labeled that way in the UI.

## 9. Risks and open technical issues

- **R1 — Python version.** Only Python 3.14 is installed. dbt-core may not support 3.14 yet. Phase 1 starts by verifying this. Fallbacks: install Python 3.12 side by side (`py install`), or use SQLMesh. No change to the design either way.
- **R2 — Scale vs free hosting.** Mitigated by publishing only pre-aggregated marts.
- **R3 — Realism.** Synthetic data that is too clean looks fake; too chaotic looks contrived. The defect catalog uses plausible rates and mixes in a few defects that pass undetected (see DEFECT_CATALOG §5).
- **R4 — Scope creep.** Dashboard stays at five views (stock, risk, exceptions, freight, pipeline health) plus the scorecard and a short roadmap panel. "Trigger a simulated incident" is a stretch item, not in scope unless approved.

## 10. Assumptions I made (confirm or change)

1. Company name "Northfield Supply Co." is a placeholder.
2. Southwest US footprint (matches your location and keeps the time-zone/DST trap realistic).
3. WH-05 being on the legacy system is a modeling choice to make the five-source story real, not a claim about any actual business.
4. 24 months of history with a live-advancing clock afterward.
5. Code repo is private; only the dashboard and scorecard are public.
