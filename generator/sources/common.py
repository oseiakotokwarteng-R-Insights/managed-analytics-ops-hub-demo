"""Shared helpers for building the five source systems from the hidden truth store."""
from __future__ import annotations

import json
import os
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config as C

SRC = Path(os.environ.get("OPS_HUB_SOURCES_OUT", C.ROOT / "sources"))
W0 = pd.Timestamp(C.WINDOW_START)
E0 = pd.Timestamp(C.HORIZON_END)
H0 = pd.Timestamp(C.HISTORY_END)  # rates that are normalised to the window use the frozen history, so extending the horizon never changes a delivered day


# ---------------------------------------------------------------- keyed randomness
# Every random decision is a pure function of (record key, salt name), so injection is deterministic,
# order-independent, and the live clock can regenerate any single day identically.
def _mix(x):
    with np.errstate(over="ignore"):
        x = x + np.uint64(0x9E3779B97F4A7C15)
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> np.uint64(31))


def u01(keys, salt: str):
    s = np.uint64(zlib.crc32(salt.encode()) + C.SEED)
    with np.errstate(over="ignore"):
        k = np.asarray(keys).astype(np.int64).view(np.uint64) ^ (s * np.uint64(0xD6E8FEB86659FD93))
        return (_mix(_mix(k)) >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def uint(keys, salt: str, lo: int, hi: int):
    """Uniform integer in [lo, hi] inclusive."""
    return lo + np.minimum((u01(keys, salt) * (hi - lo + 1)).astype(np.int64), hi - lo)


def ufloat(keys, salt: str, lo: float, hi: float):
    return lo + u01(keys, salt) * (hi - lo)


def pick(keys, salt: str, p: float):
    return u01(keys, salt) < p


# ---------------------------------------------------------------- truth access
def _dates(df):
    for c in df.columns:
        if df[c].dtype == object and (c.endswith("_date") or c in ("date", "active_from", "active_to")):
            df[c] = pd.to_datetime(df[c])
    return df


class Truth:
    """Loads truth tables lazily; the ONLY consumer of truth/ besides the scorecard."""

    _names = {"sku": "dim_sku", "wh": "dim_warehouse", "cust": "dim_customer", "vend": "dim_vendor", "cat": "dim_category",
              "cal": "dim_calendar", "orders": "truth_orders", "lines": "truth_order_lines", "po": "truth_purchase_orders",
              "pol": "truth_po_lines", "tr": "truth_transfers", "mv": "truth_movements", "ship": "truth_shipments",
              "chg": "truth_freight_charges", "pairs": "dim_sku_warehouse", "opening": "truth_opening_balance",
              "ent": "truth_scenario_entities"}

    def __init__(self):
        self._c = {}

    def __getattr__(self, k):
        if k.startswith("_") or k not in self._names:
            raise AttributeError(k)
        if k not in self._c:
            self._c[k] = _dates(pd.read_parquet(C.TRUTH_DIR / f"{self._names[k]}.parquet"))
        return self._c[k]

    @property
    def wh_code(self):
        return dict(zip(self.wh.warehouse_id, self.wh.warehouse_code))

    @property
    def wh_tz(self):
        return dict(zip(self.wh.warehouse_id, self.wh.timezone))

    def sku_code(self):
        return self.sku.set_index("sku_id").sku_code


def order_no(order_id):
    return "SO-" + (100000 + 2 * pd.Series(order_id).astype("int64")).astype(str)


def po_no(po_id):
    return "PO-" + (500000 + pd.Series(po_id).astype("int64")).astype(str)


def to_local(ts_utc: pd.Series, wh_id: pd.Series, T: Truth) -> pd.Series:
    """Naive local wall-clock time in each warehouse's own timezone."""
    out = pd.Series(pd.NaT, index=ts_utc.index, dtype="datetime64[ns]")
    for w, tz in T.wh_tz.items():
        m = (wh_id == w).values
        if m.any():
            out.loc[m] = ts_utc[m].dt.tz_convert(tz).dt.tz_localize(None).astype("datetime64[ns]")
    return out


# ---------------------------------------------------------------- defect log
class DefectLog:
    def __init__(self):
        self.parts = []

    def add(self, code, system, table, keys, etype, eids, dates=None, detail=None, handling=""):
        keys = pd.Series(np.atleast_1d(np.asarray(keys))).astype(str).reset_index(drop=True)
        n = len(keys)
        if n == 0:
            return

        def vec(x, name, default=""):
            if x is None:
                return pd.Series([default] * n)
            s = pd.Series(np.atleast_1d(np.asarray(x, dtype=object))).reset_index(drop=True)
            if len(s) == 1 and n > 1:
                s = pd.Series([s.iloc[0]] * n)
            if len(s) != n:
                raise ValueError(f"DefectLog {code}: '{name}' has {len(s)} values for {n} keys")
            return s

        eid = vec(eids, "eids").astype(str)
        if detail is None or isinstance(detail, str):
            det = [detail or ""] * n
        elif isinstance(detail, dict):
            det = [json.dumps(detail, default=str)] * n
        else:
            det = [json.dumps(d, default=str) if not isinstance(d, str) else d for d in detail]
            if len(det) != n:
                raise ValueError(f"DefectLog {code}: 'detail' has {len(det)} values for {n} keys")
        dts = pd.to_datetime(vec(dates, "dates", pd.NaT))
        self.parts.append(pd.DataFrame({
            "defect_code": code, "source_system": system, "source_table": table, "source_row_key": keys.values,
            "truth_entity_type": etype, "truth_entity_id": eid.values, "defect_date": dts.values, "expected_handling": handling, "detail": det}))

    def frame(self):
        return pd.concat(self.parts, ignore_index=True) if self.parts else pd.DataFrame()

    def counts(self):
        f = self.frame()
        return f.groupby("defect_code").size().to_dict() if len(f) else {}


# ---------------------------------------------------------------- writers
def write_by_date(df: pd.DataFrame, date_col: str, folder: Path, prefix: str, keep_col=True, **kw):
    """One CSV per extract date (the date column stays in the file as extract_date)."""
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for d, g in df.groupby(date_col, sort=True):
        g.to_csv(folder / f"{prefix}_{pd.Timestamp(d):%Y%m%d}.csv", index=False, **kw)
        n += 1
    return n


VENDOR_CITIES = ["Dallas, TX", "Houston, TX", "Los Angeles, CA", "Ontario, CA", "Salt Lake City, UT", "Denver, CO", "Portland, OR",
                 "Seattle, WA", "Atlanta, GA", "Charlotte, NC", "Memphis, TN", "Chicago, IL", "Kansas City, MO", "Oklahoma City, OK",
                 "Boise, ID", "Reno, NV", "Fort Worth, TX", "Tulsa, OK", "Phoenix, AZ", "Tucson, AZ", "Minneapolis, MN", "Omaha, NE"]
PORT_CITIES = ["Long Beach, CA", "Houston, TX", "Oakland, CA", "Savannah, GA"]


def vendor_city(T: "Truth") -> pd.Series:
    v = T.vend
    base = np.array(VENDOR_CITIES)[uint(v.vendor_id.values, "vcity", 0, len(VENDOR_CITIES) - 1)]
    port = np.array(PORT_CITIES)[uint(v.vendor_id.values, "vport", 0, len(PORT_CITIES) - 1)]
    return pd.Series(np.where(v.is_import.values, port, base), index=v.vendor_id.values)


def fmt_ts(s: pd.Series, f="%Y-%m-%d %H:%M:%S"):
    return s.dt.strftime(f)


def fmt_date(s: pd.Series, f="%Y-%m-%d"):
    return s.dt.strftime(f)


HOLIDAYS_NOTE = "Business calendar lives in truth dim_calendar"


def link_dates(T: "Truth") -> pd.Series:
    """Date the ERP item master first carries the WMS item id (new items are linked 0-35 days after first receipt)."""
    s = T.sku
    new = s.lifecycle_kind.isin(["new_launch", "successor"]).values
    first = T.pol.groupby("sku_id").received_date.min().reindex(s.sku_id).values
    lag = pd.to_timedelta(uint(s.sku_id.values, "wmslink", 0, 35), unit="D").values
    out = np.where(new & ~pd.isna(first), first + lag, np.datetime64("2020-01-15"))
    return pd.Series(pd.to_datetime(out), index=s.sku_id.values)
