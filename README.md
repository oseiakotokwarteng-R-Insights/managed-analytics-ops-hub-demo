# System 1: Unified Operations Hub (synthetic-data demo)

Five messy systems of a made-up distributor (an ERP, a warehouse system, two freight carriers, a legacy database and spreadsheets), reconciled every night into one trusted view of stock, risk, exceptions, freight and pipeline health, and scored against a hidden answer key. **All data is synthetic.**

- What it is and why it is built this way: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- What it measured, including the misses: [`docs/PHASE8_REPORT.md`](docs/PHASE8_REPORT.md) (the scorecard) and one report per phase (`docs/PHASE1_REPORT.md` to `PHASE9_REPORT.md`)
- What every table holds: [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md)
- How to operate it: [`docs/RUNBOOK.md`](docs/RUNBOOK.md); how it would be published: [`docs/PUBLISHING.md`](docs/PUBLISHING.md)
- The design and the targets, written before anything was built: [`docs/SPEC.md`](docs/SPEC.md), [`docs/DEFECT_CATALOG.md`](docs/DEFECT_CATALOG.md)

## See it

```
python -m http.server 8765 --directory dashboard
```

then open `http://localhost:8765`. The dashboard is plain static files; the data it reads is in `dashboard/data/` (rebuilt by the export step below).

## Set up

Python 3.14 (verified). `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt` (everything is pinned).

## Rebuild everything from nothing

About 35 minutes of compute on a laptop, in this order. Every step is deterministic: the same seed gives the same files.

| Step | Command | Time |
|---|---|---|
| 1. Simulate the business (answer key) | `python -m generator.run_history` | 40 s |
| 2. Derive the five source systems and log every planted defect | `python -m generator.build_sources` | 5 min |
| 3. Load them night by night into the warehouse | `python -m pipeline.run backfill --fresh` | 6 min |
| 4. Build, test and monitor every model | `python -m pipeline.build` | 3 min |
| 5. Export the dashboard data and the scorecard | `python -m pipeline.export.dashboard` and `python -m generator.validate_scorecard` | 2 min, 12 min the first time |
| 6. (optional) Generate the hidden future for the live clock | `python -m generator.extend_horizon --to 2027-09-30` | 10 min |

`generator.build_sources` replaces the `sources/` folder it writes to; never run it with the live clock advanced (reset first, see the runbook).

## Run the checks

Each phase has a gate that scores it against the answer key and writes its report. Run them with the live clock reset (`python -m pipeline.live reset`): they measure the end of history.

| Gate | Command |
|---|---|
| Phase 1, the synthetic business | `python -m generator.validate [--full]` |
| Phase 2, the five sources | `python -m generator.validate_sources [--full]` |
| Phase 3, ingestion | `python -m generator.validate_ingestion [--full]` |
| Phase 4, models and the stock table | `python -m generator.validate_models [--full]` |
| Phase 5, data quality and monitoring | `python -m generator.validate_dq [--full]` |
| Phase 6, dashboard and analytics | `python -m generator.validate_dashboard` |
| Phase 7, the live clock (clock advanced past 2027-02) | `python -m generator.validate_live` |
| Phase 8, the validation scorecard | `python -m generator.validate_scorecard` |
| Phase 9, packaging | `python -m generator.validate_package` |
| Unit and sandbox tests | `python -m pytest tests -q` |

`--full` adds the slow reproducibility proofs (a full rebuild must give identical results).

## Day to day

- Live clock: `python -m pipeline.live init`, then `python -m pipeline.live tick --catch-up` once a day (about 2.5 minutes a night; budget 30). `status`, `render` and `reset` are in the runbook.
- Publish: `python -m pipeline.package` builds `dist/public/`, the only thing that is ever published.
- Documents: `python -m generator.data_dictionary` regenerates the data dictionary from the warehouse.

## Layout

```
generator/    the synthetic business, the five source builders, every gate and the scorecard (the only code that reads the answer key)
pipeline/     ingest (contracts, loader), dbt project (staging to marts and ops), live clock, exports, packaging (never reads the answer key; a test enforces it)
dashboard/    the static front end (HTML, CSS, JavaScript) and its exported data
docs/         spec, defect catalog, architecture, runbook, publishing guide, data dictionary, phase reports and charts
tests/        ingestion guarantees, monitor sensitivity, live-clock logic
truth/ truth_live/   the hidden answer key           sources/ sources_live/   generated source systems and future
warehouse/    the DuckDB database and live-clock state          dist/    the public bundle
```

`truth*`, `sources*`, `warehouse`, `dist` and `dashboard/data` are generated and are excluded from version control (`.gitignore`).
