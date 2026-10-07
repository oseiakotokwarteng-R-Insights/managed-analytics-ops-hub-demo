"""Order-independent content fingerprints for raw tables (lineage columns excluded)."""
from __future__ import annotations


def raw_tables(con) -> list[str]:
    rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw' ORDER BY 1").fetchall()
    return [r[0] for r in rows if not r[0].startswith("_")]


def business_columns(con, table: str) -> list[str]:
    return sorted(r[1] for r in con.execute(f"PRAGMA table_info('raw.{table}')").fetchall() if not r[1].startswith("_"))


def content_hash(con, table: str) -> tuple[int, int]:
    """(row count, sum of per-row hashes over the as-received columns). Insensitive to row order, file order and column order."""
    cols = business_columns(con, table)
    expr = "hash(" + " || '|' || ".join(f"coalesce(\"{c}\", '~NULL~')" for c in cols) + ")"
    n, h = con.execute(f"SELECT COUNT(*), COALESCE(SUM(CAST({expr} AS HUGEINT)), 0) FROM raw.{table}").fetchone()
    return int(n), int(h)
