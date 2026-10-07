"""Writes docs/DATA_DICTIONARY.md from the warehouse itself: every table and view, its columns and types, its row count and a plain description taken from the comment at the
top of the model that builds it.  Usage: python -m generator.data_dictionary
Reads only the warehouse (never the hidden answer key), so it can be run by anyone with the built database."""
from __future__ import annotations

import re

import duckdb

from . import config as C

DB = C.ROOT / "warehouse" / "ops_hub.duckdb"
MODELS = C.ROOT / "pipeline" / "dbt" / "models"
SEEDS = C.ROOT / "pipeline" / "dbt" / "seeds"

LAYERS = [
    ("raw", "Raw layer", "Files exactly as received, every column text, append-only. Each row carries `_file_id` and `_row_num` so any figure can be traced to the file and line it came from. `raw._load_*`, `_file_registry`, `_schema_drift` and `_alerts` are the loader's own audit trail."),
    ("staging", "Staging", "One model per source table: types fixed, names made consistent, nothing joined or judged yet."),
    ("intermediate", "Intermediate", "Working steps that resolve identities, repair what the evidence supports and match records across systems. Not meant to be read directly."),
    ("core", "Core", "Conformed dimensions and facts, plus the reconciliation tables that list what disagrees. The review queue lives here."),
    ("quarantine", "Quarantine", "Rows set aside with a reason code instead of being used or silently dropped."),
    ("marts", "Marts", "The answers: stock by day, risk, inbound, freight, phantom-stock alerts. The dashboard reads only these (and the ops layer)."),
    ("ops", "Operations", "Monitoring: alert log, nightly health, freshness, volume, duplicate files, format drift, weekly defect rates, layer reconciliation, recorded build and test results."),
    ("ref", "Reference seeds", "Small tables under version control: reason codes and their owners, monitored feeds, holidays, service standards, effort assumptions."),
]


def describe(schema: str, name: str) -> str:
    if schema == "ref":
        return "Reference table loaded from a CSV seed under version control."
    if schema == "raw":
        if name.startswith("_"):
            return {"_load_runs": "One row per nightly load run.", "_load_files": "One row per file version loaded (or held, or failed).", "_file_registry": "The current state of every file the loader has seen.",
                    "_schema_drift": "Every column-layout change the loader noticed, and what it did about it.", "_alerts": "Loader alerts: held files, failures, releases."}.get(name, "Loader audit table.")
        return "Rows exactly as received from the source files, all text, with file and row lineage."
    hits = list(MODELS.rglob(f"{name}.sql"))
    if not hits:
        return ""
    lines = []
    for ln in hits[0].read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("{{ config") or not s:
            continue
        if s.startswith("--"):
            lines.append(s.lstrip("- ").strip())
        elif s.startswith("{#"):
            lines.append(re.sub(r"[{}#]", "", s).strip())
        else:
            break
    return " ".join(lines)[:700]


def main():
    c = duckdb.connect(str(DB), read_only=True)
    out = ["# System 1 — Data Dictionary\n",
           "Generated from the built warehouse by `python -m generator.data_dictionary`. All data is synthetic. Row counts are as of the end of history (2026-09-30), before the live clock moves.\n",
           "Where to start: the **marts** answer the business questions; **core** holds the cleaned facts they are built from; **ops** explains whether today's numbers can be trusted; **raw** is the unaltered evidence.\n"]
    total = 0
    for schema, title, blurb in LAYERS:
        tabs = c.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = ? ORDER BY table_name", [schema]).fetchall()
        if not tabs:
            continue
        out += [f"\n## {title} (`{schema}`)\n", blurb + "\n"]
        for name, kind in tabs:
            cols = c.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position", [schema, name]).fetchall()
            n = c.execute(f'SELECT count(*) FROM "{schema}"."{name}"').fetchone()[0]
            total += 1
            desc = describe(schema, name)
            out.append(f"### `{schema}.{name}`\n")
            out.append(f"{'View' if kind == 'VIEW' else 'Table'}, {n:,} rows. {desc}\n".rstrip() + "\n")
            out.append("| Column | Type |\n|---|---|")
            out += [f"| `{a}` | {b} |" for a, b in cols]
            out.append("")
    out.insert(3, f"{total} tables and views are documented.\n")
    (C.ROOT / "docs" / "DATA_DICTIONARY.md").write_text("\n".join(out), encoding="utf-8")
    print(f"documented {total} tables and views")


if __name__ == "__main__":
    main()
