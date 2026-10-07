"""Raw-layer ingestion engine.

Guarantees
  * Append-only, as-received: every raw column is VARCHAR; every row carries _file_id and _row_num (lineage to raw._load_files).
  * Idempotent: a file is identified by path + content hash. Re-running changes nothing; a changed file is loaded as a new version
    (old rows stay); a held or failed file is retried on later runs.
  * Atomic per file: rows, audit and registry commit together or not at all.
  * Schema drift is never silent: columns are checked against versioned contracts. Additive drift loads with an alert; breaking drift
    holds the file (raw._schema_drift + raw._alerts) until a contract version covering the new shape is approved.
  * Runs are dated (as_of). Files arrive on a per-source schedule; a run loads everything that has arrived by then.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from .. import config as cfg

SHEET_COLS = [f"c{i}" for i in range(1, 11)]


@dataclass
class FileItem:
    table: str
    rel: str
    path: Path
    arrival: date
    size: int
    mtime_ns: int


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)


class Ingestor:
    def __init__(self, db_path=None, sources=None, contracts=None):
        self.db_path = Path(db_path or cfg.WAREHOUSE)
        self.sources = Path(sources or cfg.SOURCES)
        self.contracts = contracts if contracts is not None else json.loads(cfg.CONTRACTS.read_text())
        self.tables = self.contracts["tables"]
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.db_path))
        self.con.execute("SET TimeZone = 'UTC'")
        self._init_schema()
        self._reg = None
        self._index = None

    # ------------------------------------------------------------------ schema
    def raw_table(self, name: str) -> str:
        return self.tables[name].get("raw_table", name)

    def _init_schema(self):
        c = self.con
        c.execute("CREATE SCHEMA IF NOT EXISTS raw")
        c.execute("CREATE SEQUENCE IF NOT EXISTS raw.file_seq START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS raw.run_seq START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS raw.drift_seq START 1")
        c.execute("CREATE SEQUENCE IF NOT EXISTS raw.alert_seq START 1")
        c.execute("""CREATE TABLE IF NOT EXISTS raw._load_runs (run_id BIGINT, as_of DATE, run_ts TIMESTAMP, finished_ts TIMESTAMP, status VARCHAR,
            files_seen INTEGER, files_loaded INTEGER, files_held INTEGER, files_failed INTEGER, files_released INTEGER, rows_loaded BIGINT, duration_s DOUBLE)""")
        c.execute("""CREATE TABLE IF NOT EXISTS raw._load_files (file_id BIGINT, run_id BIGINT, table_name VARCHAR, rel_path VARCHAR, sha256 VARCHAR, version INTEGER,
            size_bytes BIGINT, rows_loaded BIGINT, status VARCHAR, contract_version VARCHAR, arrival DATE, loaded_ts TIMESTAMP, duration_ms DOUBLE,
            profile_json VARCHAR, message VARCHAR)""")
        c.execute("""CREATE TABLE IF NOT EXISTS raw._file_registry (rel_path VARCHAR, table_name VARCHAR, sha256 VARCHAR, version INTEGER, size_bytes BIGINT,
            mtime_ns BIGINT, status VARCHAR, file_id BIGINT, updated_run_id BIGINT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS raw._schema_drift (drift_id BIGINT, run_id BIGINT, detected_as_of DATE, table_name VARCHAR, rel_path VARCHAR,
            kind VARCHAR, added VARCHAR, missing VARCHAR, action VARCHAR, resolved_run_id BIGINT, resolved_as_of DATE, resolution VARCHAR)""")
        c.execute("""CREATE TABLE IF NOT EXISTS raw._alerts (alert_id BIGINT, run_id BIGINT, as_of DATE, severity VARCHAR, table_name VARCHAR, rel_path VARCHAR,
            code VARCHAR, message VARCHAR, resolved_run_id BIGINT, resolved_as_of DATE)""")
        for name, t in self.tables.items():
            rt = self.raw_table(name)
            v1 = t["versions"][0]
            cols = list(dict.fromkeys(v1["required"] + v1["optional"]))
            ddl = ", ".join(f'"{x}" VARCHAR' for x in cols)
            c.execute(f"CREATE TABLE IF NOT EXISTS raw.{rt} ({ddl}, _file_id BIGINT, _row_num INTEGER)")

    # ------------------------------------------------------------------ discovery
    def arrival_of(self, name: str, p: Path) -> date:
        a = self.tables[name]["arrival"]
        if a["rule"] == "static":
            return date.fromisoformat(a["date"])
        m = re.search(a["regex"], p.name)
        if a["rule"] == "name_date":
            return datetime.strptime(m.group(1), a["fmt"]).date()
        y, mo = map(int, m.group(1).split("-"))
        return _month_end(y, mo) + timedelta(days=a["days"])

    def discover(self) -> list[FileItem]:
        items = []
        for name in self.tables:
            for p in sorted(self.sources.glob(self.tables[name]["glob"])):
                st = p.stat()
                items.append(FileItem(name, p.relative_to(self.sources).as_posix(), p, self.arrival_of(name, p), st.st_size, st.st_mtime_ns))
        items.sort(key=lambda i: (i.arrival, i.rel))
        return items

    def _registry(self) -> dict:
        if self._reg is None:
            df = self.con.execute("SELECT * FROM raw._file_registry").fetchdf()
            self._reg = {r.rel_path: r._asdict() for r in df.itertuples(index=False)}
        return self._reg

    # ------------------------------------------------------------------ contracts
    def _versions(self, name, as_of):
        vs = [v for v in self.tables[name]["versions"] if date.fromisoformat(v["approved_on"]) <= as_of]
        return sorted(vs, key=lambda v: v["approved_on"], reverse=True)

    def match_contract(self, name: str, cols: list[str], as_of: date):
        """-> (version_id | None, drift dict | None). Version-less drift (None) means HOLD."""
        colset = set(cols)
        vs = self._versions(name, as_of)
        if self.tables[name]["kind"] == "xlsx":
            return vs[0]["id"], None
        for v in vs:
            req, opt = set(v["required"]), set(v["optional"])
            if req <= colset <= (req | opt):
                return v["id"], None
        for v in vs:
            req, opt = set(v["required"]), set(v["optional"])
            if req <= colset:
                return v["id"], {"kind": "ADDITIVE", "added": sorted(colset - req - opt), "missing": []}
        v = vs[0]
        req, opt = set(v["required"]), set(v["optional"])
        pending = [x["id"] for x in self.tables[name]["versions"] if date.fromisoformat(x["approved_on"]) > as_of
                   and set(x["required"]) <= colset <= set(x["required"]) | set(x["optional"])]
        return None, {"kind": "BREAKING", "added": sorted(colset - req - opt), "missing": sorted(req - colset), "pending_contract": pending}

    # ------------------------------------------------------------------ readers
    def _columns(self, item: FileItem) -> list[str]:
        kind = self.tables[item.table]["kind"]
        if kind == "csv":
            with open(item.path, newline="", encoding="utf-8") as f:
                return next(csv.reader(f))
        if kind == "jsonl":
            keys: dict = {}
            with open(item.path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if line.strip():
                        keys.update(dict.fromkeys(json.loads(line).keys()))
                    if i >= 200:
                        break
            if not keys:
                raise ValueError("empty JSON-lines file")
            return list(keys)
        if kind == "json_array":
            data = json.loads(item.path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("expected a JSON array")
            keys = {}
            for r in data:
                keys.update(dict.fromkeys(r.keys()))
            return list(keys)
        return []  # xlsx: structure is interpreted in staging

    def _stage(self, item: FileItem, cols: list[str]) -> tuple[str, int]:
        """Load the file into a temp table named _stage with columns [cols] + _row_num; return (kind, rows)."""
        kind = self.tables[item.table]["kind"]
        c = self.con
        c.execute("DROP TABLE IF EXISTS _stage")
        p = str(item.path).replace("'", "''")
        qcols = ", ".join(f'"{x}"' for x in cols)
        if kind == "csv":
            c.execute(f"CREATE TEMP TABLE _stage AS SELECT {qcols}, CAST(row_number() OVER () AS INTEGER) AS _row_num FROM read_csv('{p}', header=true, all_varchar=true)")
        elif kind == "jsonl":
            spec = "{" + ", ".join(f"'{x}': 'VARCHAR'" for x in cols) + "}"
            c.execute(f"CREATE TEMP TABLE _stage AS SELECT {qcols}, CAST(row_number() OVER () AS INTEGER) AS _row_num FROM read_json('{p}', format='newline_delimited', columns={spec})")
        elif kind == "json_array":
            data = json.loads(item.path.read_text(encoding="utf-8"))
            rows = [{k: (None if r.get(k) is None else json.dumps(r[k], separators=(",", ":")) if isinstance(r[k], (dict, list)) else str(r[k])) for k in cols} for r in data]
            df = pd.DataFrame(rows, columns=cols, dtype=object)
            df["_row_num"] = range(1, len(df) + 1)
            c.register("_stage_df", df)
            c.execute("CREATE TEMP TABLE _stage AS SELECT * FROM _stage_df")
            c.unregister("_stage_df")
        else:
            df = self._read_xlsx(item)
            c.register("_stage_df", df)
            c.execute("CREATE TEMP TABLE _stage AS SELECT * FROM _stage_df")
            c.unregister("_stage_df")
        return kind, c.execute("SELECT COUNT(*) FROM _stage").fetchone()[0]

    def _read_xlsx(self, item: FileItem) -> pd.DataFrame:
        from openpyxl import load_workbook
        wb = load_workbook(item.path, read_only=True, data_only=False)
        ws = wb.active
        kind = self.tables[item.table]["sheet_kind"]
        out = []
        for row in ws.iter_rows(min_row=1, max_col=10):
            vals, types = [], []
            for cell in row:
                v = cell.value
                if v is None:
                    vals.append(None)
                    types.append("b")
                elif isinstance(v, (datetime, date)):
                    vals.append(v.isoformat())
                    types.append("d")
                elif isinstance(v, bool):
                    vals.append(str(v))
                    types.append("s")
                elif isinstance(v, (int, float)):
                    vals.append(repr(v) if isinstance(v, float) else str(v))
                    types.append("n")
                else:
                    s = str(v)
                    vals.append(s)
                    types.append("f" if s.startswith("=") else "s")
            if any(x is not None for x in vals):
                vals += [None] * (10 - len(vals))
                types += ["b"] * (10 - len(types))
                out.append([kind, ws.title, row[0].row] + vals + ["".join(types)])
        wb.close()
        df = pd.DataFrame(out, columns=["sheet_kind", "sheet_name", "sheet_row"] + SHEET_COLS + ["cell_types"], dtype=object)
        df["sheet_row"] = df.sheet_row.astype(str)
        df["_row_num"] = range(1, len(df) + 1)
        return df

    # ------------------------------------------------------------------ loading
    @staticmethod
    def _sha(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _record_attempt(self, fid, run_id, item, sha, version, rows, status, cver, run_ts, ms, profile, msg):
        self.con.execute("INSERT INTO raw._load_files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [fid, run_id, item.table, item.rel, sha, version, item.size, rows, status, cver, item.arrival, run_ts, ms,
                          json.dumps(profile) if profile else None, msg])

    def _set_registry(self, item, sha, version, status, fid, run_id):
        self.con.execute("DELETE FROM raw._file_registry WHERE rel_path = ?", [item.rel])
        self.con.execute("INSERT INTO raw._file_registry VALUES (?,?,?,?,?,?,?,?,?)", [item.rel, item.table, sha, version, item.size, item.mtime_ns, status, fid, run_id])
        self._registry()[item.rel] = dict(rel_path=item.rel, table_name=item.table, sha256=sha, version=version, size_bytes=item.size, mtime_ns=item.mtime_ns,
                                          status=status, file_id=fid, updated_run_id=run_id)

    def _alert(self, run_id, as_of, severity, table, rel, code, msg):
        self.con.execute("INSERT INTO raw._alerts VALUES (nextval('raw.alert_seq'),?,?,?,?,?,?,?,NULL,NULL)", [run_id, as_of, severity, table, rel, code, msg])

    def _profile(self, name: str, rows: int) -> dict:
        prof = {"rows": rows}
        for col in self.tables[name].get("time_cols", []):
            r = self.con.execute(f'SELECT MIN("{col}"), MAX("{col}") FROM _stage').fetchone()
            prof[col] = [r[0], r[1]]
        return prof

    def _load_file(self, run_id, as_of, run_ts, item: FileItem, sha: str, version: int, fail_hook=None) -> dict:
        t0 = time.perf_counter()
        c = self.con
        fid = c.execute("SELECT nextval('raw.file_seq')").fetchone()[0]
        try:
            cols = self._columns(item)
            cver, drift = self.match_contract(item.table, cols, as_of)
            if cver is None:
                prior = self._registry().get(item.rel)
                if not (prior and prior["status"] == "HELD_DRIFT" and prior["sha256"] == sha):
                    c.execute("INSERT INTO raw._schema_drift VALUES (nextval('raw.drift_seq'),?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
                              [run_id, as_of, item.table, item.rel, drift["kind"], ",".join(drift["added"]), ",".join(drift["missing"]), "FILE_HELD"])
                    pend = drift.get("pending_contract")
                    msg = (f"{item.rel}: columns changed (missing {drift['missing']}, new {drift['added']}); file held, nothing loaded."
                           + (f" Shape matches contract {pend[0]}, which is not yet approved." if pend else " No contract version matches."))
                    self._alert(run_id, as_of, "ERROR", item.table, item.rel, "SCHEMA_DRIFT_HELD", msg)
                    self._record_attempt(fid, run_id, item, sha, version, 0, "HELD_DRIFT", None, run_ts, (time.perf_counter() - t0) * 1000, None, msg)
                    self._set_registry(item, sha, version, "HELD_DRIFT", fid, run_id)
                return {"status": "HELD", "rows": 0}
            rt = self.raw_table(item.table)
            c.execute("BEGIN")
            existing = {r[1] for r in c.execute(f"PRAGMA table_info('raw.{rt}')").fetchall()}
            new_cols = [x for x in cols if x not in existing]
            for x in new_cols:
                c.execute(f'ALTER TABLE raw.{rt} ADD COLUMN "{x}" VARCHAR')
            _, rows = self._stage(item, cols if self.tables[item.table]["kind"] != "xlsx" else [])
            prof = self._profile(item.table, rows)
            qcols = ", ".join(f'"{x}"' for x in (cols if self.tables[item.table]["kind"] != "xlsx" else ["sheet_kind", "sheet_name", "sheet_row"] + SHEET_COLS + ["cell_types"]))
            c.execute(f"INSERT INTO raw.{rt} ({qcols}, _file_id, _row_num) SELECT {qcols}, {fid}, _row_num FROM _stage")
            released = 0
            prior = self._registry().get(item.rel)
            if prior and prior["status"] == "HELD_DRIFT":
                c.execute("UPDATE raw._schema_drift SET resolved_run_id=?, resolved_as_of=?, resolution=? WHERE rel_path=? AND resolved_run_id IS NULL",
                          [run_id, as_of, f"loaded under contract {cver}", item.rel])
                c.execute("UPDATE raw._alerts SET resolved_run_id=?, resolved_as_of=? WHERE rel_path=? AND resolved_run_id IS NULL", [run_id, as_of, item.rel])
                released = 1
            if drift and drift["kind"] == "ADDITIVE":
                c.execute("INSERT INTO raw._schema_drift VALUES (nextval('raw.drift_seq'),?,?,?,?,?,?,?,?,?,?,?)",
                          [run_id, as_of, item.table, item.rel, "ADDITIVE", ",".join(drift["added"]), "", "COLUMNS_ADDED_TO_RAW", run_id, as_of, "accepted: additive columns only"])
                self._alert(run_id, as_of, "INFO", item.table, item.rel, "SCHEMA_ADDITIVE", f"{item.rel}: new columns {drift['added']} added to raw.{rt}; staging ignores them until the contract is updated.")
            elif new_cols and self.tables[item.table]["kind"] != "xlsx":
                c.execute("INSERT INTO raw._schema_drift VALUES (nextval('raw.drift_seq'),?,?,?,?,?,?,?,?,?,?,?)",
                          [run_id, as_of, item.table, item.rel, "EVOLUTION", ",".join(new_cols), "", "COLUMNS_ADDED_TO_RAW", run_id, as_of, f"approved contract {cver}"])
            ms = (time.perf_counter() - t0) * 1000
            status = "RELOADED_CHANGED" if version > 1 else "LOADED"
            self._record_attempt(fid, run_id, item, sha, version, rows, status, cver, run_ts, ms, prof, None)
            self._set_registry(item, sha, version, "LOADED", fid, run_id)
            if fail_hook:
                fail_hook(item.rel, "before_commit")
            c.execute("COMMIT")
            return {"status": "LOADED", "rows": rows, "released": released}
        except Exception as e:  # atomic: nothing from this file survives
            try:
                c.execute("ROLLBACK")
            except Exception:
                pass
            self._reg = None
            msg = f"{type(e).__name__}: {str(e)[:300]}"
            self._record_attempt(fid, run_id, item, sha, version, 0, "FAILED", None, run_ts, (time.perf_counter() - t0) * 1000, None, msg)
            self._set_registry(item, sha, version, "FAILED", fid, run_id)
            self._alert(run_id, as_of, "ERROR", item.table, item.rel, "LOAD_FAILED", f"{item.rel}: {msg}")
            return {"status": "FAILED", "rows": 0}

    # ------------------------------------------------------------------ runs
    def run(self, as_of: date, items: list[FileItem] | None = None, fail_hook=None) -> dict:
        """One nightly run: load everything that has arrived by as_of. Scheduled at 02:00 UTC the next morning."""
        t0 = time.perf_counter()
        run_id = self.con.execute("SELECT nextval('raw.run_seq')").fetchone()[0]
        run_ts = datetime.combine(as_of, datetime.min.time()) + timedelta(days=1, hours=2)
        items = items if items is not None else self.discover()
        reg = self._registry()
        seen = loaded = held = failed = released = rows = 0
        for it in items:
            if it.arrival > as_of:
                break
            seen += 1
            r = reg.get(it.rel)
            if r and r["status"] == "LOADED" and r["size_bytes"] == it.size and r["mtime_ns"] == it.mtime_ns:
                continue
            sha = self._sha(it.path)
            if r and r["status"] == "LOADED" and r["sha256"] == sha:
                self.con.execute("UPDATE raw._file_registry SET size_bytes=?, mtime_ns=? WHERE rel_path=?", [it.size, it.mtime_ns, it.rel])
                r["size_bytes"], r["mtime_ns"] = it.size, it.mtime_ns
                continue
            version = (r["version"] + 1) if (r and r["sha256"] != sha) else (r["version"] if r else 1)
            if r and r["status"] in ("HELD_DRIFT", "FAILED") and r["sha256"] != sha:
                version = r["version"]
            out = self._load_file(run_id, as_of, run_ts, it, sha, version, fail_hook)
            if out["status"] == "LOADED":
                loaded += 1
                rows += out["rows"]
                released += out.get("released", 0)
            elif out["status"] == "HELD":
                held += 1
            else:
                failed += 1
        still_held = self.con.execute("SELECT COUNT(*) FROM raw._file_registry WHERE status='HELD_DRIFT'").fetchone()[0]
        dur = time.perf_counter() - t0
        status = "PARTIAL" if failed else ("OK_WITH_HELD_FILES" if still_held else "OK")
        self.con.execute("INSERT INTO raw._load_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         [run_id, as_of, run_ts, run_ts + timedelta(seconds=dur), status, seen, loaded, held, failed, released, rows, dur])
        return {"run_id": run_id, "as_of": as_of, "status": status, "seen": seen, "loaded": loaded, "held": held, "failed": failed, "released": released, "rows": rows}

    def backfill(self, start: date, end: date, progress=None) -> list[dict]:
        """Replay history as one run per night, exactly as the scheduler would have executed it."""
        items = self.discover()
        out = []
        d = start
        while d <= end:
            out.append(self.run(d, items))
            if progress and (d.day == 1 or d == end):
                progress(d, out[-1])
            d += timedelta(days=1)
        return out

    def close(self):
        self.con.close()
