# System 1 — Phase 9 Report: Packaging

Gates: **ALL PASS** (12/12). **Nothing has been published**: no repository, no host, no DNS, no upload. This phase makes the project ready to publish and says exactly what is left to decide.

## What was built

- **A public bundle** (`python -m pipeline.package`): the dashboard and its exported JSON, nothing else, deterministic, with cache and security headers, a robots file that keeps search engines out until launch, and a manifest of every file.

- **A repository ready to be private** (`.gitignore`, complete pinned `requirements.txt`): a first commit would contain code and documents only. The answer key, generated sources, warehouse and bundle are excluded.

- **Documents:** a rewritten README (set up, rebuild from nothing with timings, every gate, layout), `ARCHITECTURE.md` (the idea, data flow, the promise of each layer, decisions, limits), `DATA_DICTIONARY.md` (generated from the warehouse: every table and view), `PUBLISHING.md` (public and private, hosting, launch checklist, the open decisions), and the existing runbook and phase reports.

- **Launch settings in one file:** `dashboard/config.json` holds the contact link and site URL, so launch needs no code change.

## Open decisions (also in `PUBLISHING.md`)

Subdomain and host; launch date (the generated year ends 2027-09-30); where the nightly state lives (a machine that stays on, a hosted runner with storage, or a stateless rebuild); the contact link for the call-to-action; whether to be searchable from day one; and whether to rename the placeholder company.

## Honest notes

- **The requirements file was incomplete until this phase.** It listed the numeric libraries but not the dbt packages or pytest, so a fresh install would not have been able to run the pipeline. It is now complete and checked against what the code imports.

- **The clean-copy check caught a real mistake.** The first version of the ignore rules said `sources/`, which also hid `generator/sources/` (the five source builders), so a first commit would have been missing code. The rules are now anchored to the project root, and the gate imports every module from a copy of exactly what would be committed.

- **The published scorecard shows all nine phases, including every miss.** Nothing was removed or reworded for the public view.

- **Not tested here:** a real upload and a real domain, because nothing may be published without the owner's go-ahead; a rebuild from nothing on a second machine (the timings in the README are from this one).


## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| building the bundle twice gives the identical bundle | 2,827 files, 41.0 MB; fingerprints a28087f5162c7e8d and a28087f5162c7e8d | identical | PASS |
| only web file types are published, and the bundle is far inside static-host limits | types {'.css': 1, '.html': 1, '.js': 11, '.json': 2813, '.txt': 1, '_headers': 1}; largest file 0.87 MB; 2,827 files | web types only; < 20,000 files; no file over 5 MB | PASS |
| nothing private is in the bundle: no answer-key names, local paths, database names, addresses or keys | 0 matches over 2,828 text files | 0 | PASS |
| every file the pages refer to exists, including one history file per item | 11 scripts; 0 broken references; 2,800 item histories for 2,800 items | none broken, one per item | PASS |
| the bundle serves from a plain static web server: every page, script and data file answers and every JSON file parses | 53 requests, 0 failures | 0 failures | PASS |
| search engines are kept out until launch, and data is never cached stale | default robots: Disallow: /; --indexable: Allow: /; data cache rule present: True | Disallow by default, Allow with the flag, no-cache on data | PASS |
| launch settings still empty (set at launch, see PUBLISHING.md) | contact link: not set; site url: not set | reported | INFO |
| a first commit holds code and documents only: small, with no generated data and no answer key | 195 files, 1.9 MB; forbidden files: 0 | < 25 MB and none forbidden | PASS |
| no keys or passwords in anything that would be committed | 0 matches over 195 files | 0 | PASS |
| every module imports from a clean copy of what would be committed (no hidden dependence on generated files) | 37 modules; failures: none | all import | PASS |
| every dependency is pinned, and everything the code imports is listed | 10 pinned lines (dbt-core, dbt-duckdb and pytest included: True); imported but not listed: none | all pinned with ==, none missing | PASS |
| the data dictionary documents every table and is current (regenerating changes nothing) | 108 documented of 108 tables and views; unchanged on regeneration: True | all, unchanged | PASS |
| the documents exist and every link between them works | 15 of 15 required documents; 0 broken links | none missing, none broken | PASS |
