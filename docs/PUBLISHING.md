# Publishing and launch

## Status: launched 2026-10-07

- **Live site:** https://ops-demo.managedanalytics.co (a Cloudflare Worker named `ops-hub-demo` serving the static bundle; custom domain on the `managedanalytics.co` zone; HTTPS, indexable).
- **Private repository:** `oseiakotokwarteng-R-Insights/managed-analytics-ops-hub-demo` (code and documents only).
- **Main website:** `managedanalytics.co` links to the demo from the case-studies section and from the Data Engineering and Analytics service cards (repository `managed-analytics-website`, auto-deploys on push to `main`).
- **Live clock:** initialised with launch date 2026-10-07 (the dashboard shows the end of history, 2026-09-30, on launch day, then advances one simulated day per real day).
- **Nightly job:** Windows Task Scheduler task `OpsHubNightly`, daily at 03:00 on the build machine, runs `deploy/nightly.ps1` (advance the clock, rebuild, package, upload, verify). It uses the Cloudflare login saved by `wrangler login` and catches up after missed days (`StartWhenAvailable`). Log: `warehouse/nightly.log`. Remove it with `Unregister-ScheduledTask -TaskName OpsHubNightly -Confirm:$false`.
- **Manual deploy:** `deploy/deploy_demo.ps1` (package, upload, check that the live site serves the same fingerprint).

The rest of this document is the plan the launch followed, kept for reference.

## Original plan



## Public and private

| Public (the bundle `dist/public/`) | Private (never leaves the build machine or the private repository) |
|---|---|
| `index.html`, CSS and JavaScript of the dashboard | The hidden answer key: `truth/`, `truth_live/` |
| Exported JSON: mart summaries, per-item stock histories, the scorecard (scores only) | The generated source systems and the generated future: `sources/`, `sources_live/` |
| `config.json` (contact button, site URL), `_headers`, `robots.txt`, `manifest.json` | The warehouse, its backups and replay copies: `warehouse/`, `*.duckdb` |
| | All code, tests, dbt project and documents (a private repository) |

`python -m pipeline.package` builds the public bundle and refuses to copy anything but HTML, CSS, JavaScript and JSON from `dashboard/`. `python -m generator.validate_package` checks the result: allowed file types only, no answer-key table names, no local paths or personal addresses, every reference resolves, and the bundle can be rebuilt byte for byte.

The repository's `.gitignore` already excludes everything generated, large or secret, so a first commit contains code and documents only (a few megabytes).

## Building the bundle

```
python -m pipeline.live render        # only if the live clock is running: refresh the data
python -m pipeline.package            # dist/public/, not indexable by search engines
python -m pipeline.package --indexable   # at launch
```

The bundle is 2,827 files and 41 MB (about 3 MB compressed). Any static host serves it as is.

## Hosting (a recommendation, not a decision)

The plan in the spec is a Cloudflare subdomain. With Cloudflare Pages a direct upload would be:

```
npx wrangler pages deploy dist/public --project-name <name>
```

then a CNAME for the chosen subdomain pointing at the Pages project. The headers file already sets cache rules (data files are never cached, code for five minutes). Pages allows 20,000 files and 25 MB per file; the bundle is far inside both. Alternatives that need no changes: any object store with static hosting, or a plain web server.

## Where the nightly state lives (the one design choice left open)

The live clock needs three folders between runs: the warehouse, the delivered files and the generated future (together about 2.5 GB, mostly files that can be rebuilt). Options:

1. **A machine that is on every night (recommended to start).** Task Scheduler or cron runs `python -m pipeline.live tick --catch-up`, then `python -m pipeline.package` and the upload. Simplest, costs nothing, and the runner already catches up after any missed days. Risk: the machine is the single point of failure.
2. **A scheduled job on a hosted runner with the state kept in object storage.** Restore, tick, save, publish. Robust, but pays for storage and transfer of the state each night. `docs/live-tick.workflow.yml` is the template.
3. **Stateless: rebuild everything each night.** Regenerating a year (about 10 minutes) and rebuilding from scratch fits inside a runner's time limit, and needs no storage. It would reproduce the history almost exactly but not byte for byte (15 carrier files near the end of history differ by in-transit shipments), so published scorecard figures could move slightly.

## Launch checklist

1. Decide the items below.
2. Fill `dashboard/config.json` (contact label and link, site URL) and rebuild the bundle.
3. `python -m pipeline.live init --launch-date <date>` (backs up the warehouse so the demo can be reset).
4. Schedule the nightly command (option 1, 2 or 3).
5. Build with `--indexable`, upload, point the subdomain, and open the site on a phone.
6. Create the private repository and push the first commit (code and documents only).

## Decisions needed from the owner

- The subdomain and the host (or a different hosting choice).
- The launch date, which decides when the clock starts and how long the generated year lasts (it ends 2027-09-30).
- Which of the three state options to use.
- The contact link for the "Want this on your data?" button.
- Whether the site should be indexable by search engines from day one.
- Whether to name the demo company something other than the placeholder "Northfield Supply Co." (a real trading name would need checking first).
