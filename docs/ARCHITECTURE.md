# System 1 — Architecture

All data is synthetic. This document explains how the pieces fit, why they are shaped this way, and where the boundaries are. For operating it day to day see `RUNBOOK.md`; for what every table holds see `DATA_DICTIONARY.md`; for what was measured see the phase reports and `PHASE8_REPORT.md`.

## The idea in one paragraph

A made-up distributor, Northfield Supply Co., runs on five systems that disagree: an ERP, a warehouse system, two freight carriers, an old legacy database and spreadsheets. A generator builds the *true* business first and keeps it hidden (the answer key), then derives the five systems from it and corrupts them in 36 documented ways. The pipeline sees only the five messy systems. A scorecard then compares what the pipeline did with the answer key. That is what makes the demo checkable: every claim on the dashboard can be scored.

## Data flow

```
generator/                 simulate the business (24 months + a hidden year ahead)
   │ writes                                                    truth/ and truth_live/   (answer key: never read by the pipeline)
   ▼
sources/  (5 systems in their native formats)  <───────────── sources_live/ (hidden future, released one day at a time by the live clock)
   │
   ▼  pipeline/ingest        nightly load: contracts, schema-drift hold, idempotent, append-only
raw   (as received, all text, lineage on every row)
   │
   ▼  pipeline/dbt           staging → intermediate → core → marts, plus quarantine, review queue and ops
core / marts / quarantine / ops        (DuckDB file, warehouse/ops_hub.duckdb)
   │
   ▼  pipeline/export        JSON for the dashboard (aggregates, per-item histories, scorecard)
dashboard/  (static HTML, CSS, JavaScript)  ──► pipeline/package ──► dist/public/   the only thing ever published
```

`generator/validate_*.py` are the only code that reads the answer key. They score each phase; `generator/validate_scorecard.py` scores the whole.

## Layers and what each one promises

| Layer | Promise |
|---|---|
| raw | The file as received, nothing altered. Every row traceable to a file and a line. A file whose columns match no approved contract is held with an alert, never loaded silently. |
| staging | Types and names fixed. No judgment. |
| intermediate | Identity resolution (legacy codes, WMS item ids, carrier references) and evidence-based repair, each rule written down, each repair logged. |
| core | Conformed dimensions and facts. Reconciliation tables list what disagrees. The review queue holds everything the pipeline would not decide alone, each with a reason code, an owner and a suggested action. |
| quarantine | Rows set aside with a reason code. Nothing is dropped silently. |
| marts | The answers the dashboard shows. Float sums are rounded and ordered aggregates used, so a rebuild is byte-identical. |
| ops | Whether the numbers can be trusted: alerts, nightly health, freshness, volume, duplicate files, format drift, weekly defect rates, row conservation between layers. |

## Decisions that shaped it

- **Hidden answer key, strictly separated.** The pipeline package never imports the generator and never reads the key; a test enforces it. The key is used only by scoring code, and the published scorecard contains scores, not the key.
- **DuckDB, one file.** Free, portable, fast enough (about 9 million stock rows rebuild in minutes). The cost is a single writer, so the live clock holds a lock.
- **Append-only raw with contracts.** Breaking drift is held and alerted; additive drift is loaded with an INFO alert; a changed file becomes a new version, not an overwrite.
- **Evidence over guesses.** Repairs use a second source (a receipt is checked against its PO, a missing ship confirmation against pick, pack and the ERP, a carrier reference against date, weight and city). Where no evidence exists the row stays as it is and is flagged. Wrong repairs are counted on the scorecard.
- **Estimate, don't trust the book.** Stock is rebuilt from movements and re-anchored on valid counts, with a confidence tier. It beats the systems' own number (95.1% against 87.4% of stock-days exact) but misses the 98% target, because unrecorded shrink accumulates between counts. The dashboard says so.
- **Determinism everywhere.** Every random decision is a keyed hash of the record, every simulated day has its own random stream, and rates are normalised on the frozen history. That is what lets a year of future be generated in advance, released one day at a time, and extended later without changing any delivered day (proved by `generator/extend_horizon.py` before it swaps anything in).
- **Static front end, no libraries.** Plain HTML, CSS and ES modules reading pre-aggregated JSON; phone layout is the base design. Easy to host anywhere, nothing to patch.
- **Targets written first.** `SPEC.md` section 8 and `DEFECT_CATALOG.md` hold the targets. The scorecard code reads them from those tables and a gate checks equality, so a target cannot drift to fit a result.

## What is public and what is private

See `PUBLISHING.md`. In short: only `dist/public/` (the dashboard and its JSON) is ever published; the repository is private; the answer key, generated sources and warehouse never leave the machine that builds them.

## Known limits

- The dashboard shows a snapshot per night, not live queries; it is a demonstration of results, not an application.
- The generated future ends on 2027-09-30 and must be extended to run longer.
- Item histories (about 40 MB raw, 2.6 MB compressed) are one file per item; a very large catalogue would want a different layout.
- The stock estimate decays slowly between counts; the roadmap panel is built around that finding.
- One scenario (the roofing surge) and two criteria miss their targets; they are published as such.
