# System 1: Unified Operations Hub (synthetic-data demo)

I made up a distributor with five messy systems: an ERP, a warehouse system, two freight carriers, a legacy database and some spreadsheets. Every night, this project pulls them together into one trusted view of stock, risk, exceptions, freight and pipeline health. Then I score the result against a hidden answer key. **All the data is synthetic.**

- Why it's built the way it is: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- What I measured, including where it missed: [`docs/PHASE8_REPORT.md`](docs/PHASE8_REPORT.md) is the scorecard, and there's one report per phase (`docs/PHASE1_REPORT.md` to `PHASE9_REPORT.md`)
- What's in every table: [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md)
- How to run it day to day: [`docs/RUNBOOK.md`](docs/RUNBOOK.md). How it would be published: [`docs/PUBLISHING.md`](docs/PUBLISHING.md)
- The design and the targets, which I wrote before building anything: [`docs/SPEC.md`](docs/SPEC.md) and [`docs/DEFECT_CATALOG.md`](docs/DEFECT_CATALOG.md)

## See it

```
python -m http.server 8765 --directory dashboard
```

Then open `http://localhost:8765`. The dashboard is plain static files. The data it reads is in `dashboard/data/`, and the export step below rebuilds it.

## Set up

I used Python 3.14. Run `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`. Everything is pinned.

## Rebuild everything from nothing

This takes about 35 minutes on a laptop, and the steps go in this order. Every step is deterministic, so the same seed gives you the same files.

| Step | Command | Time |
|---|---|---|
| 1. Simulate the business (the answer key) | `python -m generator.run_history` | 40 s |
| 2. Build the five source systems and log every defect I planted | `python -m generator.build_sources` | 5 min |
| 3. Load them into the warehouse, night by night | `python -m pipeline.run backfill --fresh` | 6 min |
| 4. Build, test and monitor every model | `python -m pipeline.build` | 3 min |
| 5. Export the dashboard data and the scorecard | `python -m pipeline.export.dashboard` and `python -m generator.validate_scorecard` | 2 min, or 12 min the first time |
| 6. (Optional) Generate the hidden future for the live clock | `python -m generator.extend_horizon --to 2027-09-30` | 10 min |

`generator.build_sources` replaces the `sources/` folder it writes to. Don't run it while the live clock is ahead. Reset it first (the runbook shows how).

## Run the checks

Each phase has a gate that scores it against the answer key and writes its report. Run them with the live clock reset (`python -m pipeline.live reset`), because they measure the end of the history.

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

`--full` adds the slow reproducibility proofs, which check that a full rebuild gives identical results.

## Day to day

- **Live clock:** run `python -m pipeline.live init`, then `python -m pipeline.live tick --catch-up` once a day. A night takes about 2.5 minutes, and the budget is 30. The runbook covers `status`, `render` and `reset`.
- **Publish:** `python -m pipeline.package` builds `dist/public/`, and that's the only thing I ever publish.
- **Documents:** `python -m generator.data_dictionary` regenerates the data dictionary from the warehouse.

## Layout

```
generator/    the synthetic business, the five source builders, every gate and the scorecard (the only code that reads the answer key)
pipeline/     ingest (contracts, loader), the dbt project (staging to marts and ops), the live clock, exports and packaging (it never reads the answer key, and a test makes sure of that)
dashboard/    the static front end (HTML, CSS, JavaScript) and its exported data
docs/         spec, defect catalog, architecture, runbook, publishing guide, data dictionary, phase reports and charts
tests/        ingestion guarantees, monitor sensitivity, live-clock logic
truth/ truth_live/   the hidden answer key           sources/ sources_live/   the generated source systems and the future
warehouse/    the DuckDB database and live-clock state          dist/    the public bundle
```

`truth*`, `sources*`, `warehouse`, `dist` and `dashboard/data` are all generated, so they're left out of version control (see `.gitignore`).
