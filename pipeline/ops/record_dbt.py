"""Records the result of the last `dbt test` / `dbt run` into ops.dbt_invocation and ops.dbt_test_result so build failures show up in the
pipeline-health view like any other alert.  Usage: python -m pipeline.ops.record_dbt"""
from __future__ import annotations

import json
from datetime import datetime

import duckdb

from .. import config as cfg

RESULTS = cfg.ROOT / "pipeline" / "dbt" / "target" / "run_results.json"


def record(db=None, as_of=None) -> dict:
    """as_of is the simulated night this build belongs to (the dbt history_end); an alert for a failed test is dated to it, not to the wall clock."""
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    meta = data["metadata"]
    inv = meta["invocation_id"]
    cmd = data["args"].get("which", "")
    gen = datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00")).replace(tzinfo=None)
    res = [r for r in data["results"] if not r["unique_id"].startswith("operation.")]  # hooks are not model or test results
    con = duckdb.connect(str(db or cfg.WAREHOUSE))
    con.execute("create schema if not exists ops")
    con.execute("create table if not exists ops.dbt_invocation (invocation_id varchar, command varchar, generated_at timestamp, elapsed_s double, n_pass integer, n_fail integer, n_error integer, n_skip integer, n_warn integer, as_of date)")
    con.execute("alter table ops.dbt_invocation add column if not exists as_of date")
    con.execute("update ops.dbt_invocation set as_of = date '2026-09-30' where as_of is null")  # builds made before the live clock ran at the end of history
    con.execute("create table if not exists ops.dbt_test_result (invocation_id varchar, unique_id varchar, name varchar, status varchar, failures bigint, execution_time double, generated_at timestamp, message varchar)")
    con.execute("delete from ops.dbt_invocation where invocation_id = ?", [inv])
    con.execute("delete from ops.dbt_test_result where invocation_id = ?", [inv])
    cnt = lambda *s: sum(1 for r in res if r["status"] in s)
    con.execute("insert into ops.dbt_invocation values (?,?,?,?,?,?,?,?,?,?)", [inv, cmd, gen, data.get("elapsed_time"), cnt("pass", "success"), cnt("fail"), cnt("error"), cnt("skipped"), cnt("warn"), as_of or "2026-09-30"])
    if cmd == "test":
        for r in res:
            con.execute("insert into ops.dbt_test_result values (?,?,?,?,?,?,?,?)",
                        [inv, r["unique_id"], r["unique_id"].split(".")[2], r["status"], r.get("failures") or 0, r.get("execution_time"), gen, (r.get("message") or "")[:300]])
    con.close()
    return {"invocation": inv, "command": cmd, "results": len(res), "passed": cnt("pass", "success"), "failed": cnt("fail", "error")}


if __name__ == "__main__":
    print(record())
