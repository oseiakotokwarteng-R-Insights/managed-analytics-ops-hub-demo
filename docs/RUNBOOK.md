# Runbook: the live clock

All data is synthetic. This is how the demo is operated.

## What runs every night

`python -m pipeline.live tick --catch-up` (about 2.5 minutes; budget 30). For every simulated night it has not done yet, in order:

1. **Release** the source files that arrive that day from the generated future (`sources_live/`) into the drop folder (`sources/`).
2. **Load** them: one nightly run per night (`raw._load_runs`), files held if their layout does not match an approved contract.
3. **Rebuild** every dbt model and run every test (once, for the final night of a catch-up).
4. **Refresh** the alert log and the health view, then **re-export** the dashboard data (`dashboard/data/`).

The clock (`warehouse/live_clock.json`) moves only after all four succeed. Every step is safe to repeat.

## Commands

| Command | What it does |
|---|---|
| `python -m pipeline.live init [--launch-date YYYY-MM-DD]` | Start the clock at the end of history. Backs up the warehouse and lists the delivered files so the demo can be reset. |
| `python -m pipeline.live status` | Where the clock stands, today's target, how far behind, the last runs. |
| `python -m pipeline.live tick` | Advance one simulated day. |
| `python -m pipeline.live tick --catch-up` | Advance to today's target (launch date plus real days elapsed). Use this from the scheduler. |
| `python -m pipeline.live tick --to 2027-02-15` / `--days 7` | Advance to a date, or by N days. |
| `python -m pipeline.live render` | Re-export the dashboard data without advancing. |
| `python -m pipeline.live reset` | Back to the end of history: deletes released files, restores the warehouse backup, clears the clock. Run `pipeline.build` afterwards, then `init` to start again. |
| `python -m generator.extend_horizon --to 2028-09-30` | Generate more future (about ten minutes). Refuses to swap anything in if it would change a file already delivered. |

## Scheduling

The runner needs no scheduler of its own. Any of these calls it once a day; if a day is missed, the next call catches up.

**Windows Task Scheduler** (runs at 02:30 local time):

```
schtasks /Create /SC DAILY /ST 02:30 /TN "OpsHubLiveTick" /TR "cmd /c cd /d C:\path\to\system-1-ops-hub && .venv\Scripts\python.exe -m pipeline.live tick --catch-up >> warehouse\live_tick.log 2>&1"
```

**cron:** `30 2 * * *  cd /path/to/system-1-ops-hub && .venv/bin/python -m pipeline.live tick --catch-up >> warehouse/live_tick.log 2>&1`

**GitHub Actions:** `docs/live-tick.workflow.yml` is a template. A hosted runner starts empty, so the warehouse, the drop folder and the generated future must be restored before the tick and saved after it. Where that state lives is a packaging decision (Phase 9); nothing in the runner assumes a particular place.

## When something goes wrong

| Symptom | What it means | What to do |
|---|---|---|
| `another tick is running` | A lock file exists (`warehouse/live.lock`). | If no tick is running, a previous one crashed: delete the file. Locks older than three hours are ignored. |
| A tick failed | The clock did not move; files already loaded are in the registry. | Fix the cause and run the same command again. Nothing is loaded twice. |
| `beyond the generated future` | The clock reached the end of the generated year. | `python -m generator.extend_horizon --to <later date>`. |
| Red night on the dashboard | An error-level alert is open (stale feed, held file, failed test). | Read the alert on the Pipeline health view. A held file is released by approving its layout: add the version (with `approved_on`) to `pipeline/contracts/contracts.json` and map its columns in the staging model; the next run loads the held files. |
| `the extension would change files that were already delivered` | A generator rule depends on the horizon. | Read the listed files, find the rule (rates normalised to the window, global rankings, sequential ids), make it depend on the frozen history only. |

## Budget

| Run | Time |
|---|---|
| One night | about 2.5 minutes (release and load 4 s, models, tests and alerts 130 s, export 16 s) |
| 31 nights caught up | 3.8 minutes |
| 104 nights caught up | 7.6 minutes |
| Generate a year of future | about 9 minutes, once a year |
