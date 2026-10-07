"""Builds a small, realistic sandbox of source files (copied from sources/) for fast ingestion tests."""
from __future__ import annotations

import shutil
from pathlib import Path

from pipeline import config as cfg


def build(dst: Path) -> Path:
    src = cfg.ROOT / "sources"
    dst.mkdir(parents=True, exist_ok=True)

    def cp(rel):
        s = src / rel
        if s.exists():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, dst / rel)
    for f in ("item_master", "customer_master", "vendor_master", "warehouse_master"):
        cp(f"erp/{f}.csv")
    for d in ("20250310", "20250311", "20250312"):
        cp(f"erp/sales_order_header/so_header_{d}.csv")
        cp(f"erp/sales_order_line/so_line_{d}.csv")
        cp(f"erp/po_header/po_header_{d}.csv")
        cp(f"erp/po_line/po_line_{d}.csv")
        cp(f"freight/carrier_a/shipments_{d}.json")
        cp(f"freight/carrier_b/shipments_{d}.csv")
        cp(f"freight/carrier_b/tracking_{d}.csv")
        cp(f"freight/carrier_b/charges_{d}.csv")
    for d in ("2025-03-10", "2025-03-11", "2025-03-12"):
        for wh in ("WH-01", "WH-03"):
            cp(f"wms/{wh}/{d}.jsonl")
    for d in ("20260602", "20260603", "20260604", "20260605", "20260606", "20260608", "20260609", "20260610"):
        cp(f"freight/carrier_b/shipments_{d}.csv")
        cp(f"freight/carrier_b/tracking_{d}.csv")
        cp(f"freight/carrier_b/charges_{d}.csv")
    for d in ("20241006", "20241013"):
        cp(f"legacy/inv_trans_{d}.csv")
    cp("legacy/vendor.csv")
    cp("legacy/item_cost.csv")
    cp("spreadsheets/count_sheets/WH-01/2024-10_count.xlsx")
    cp("spreadsheets/price_overrides/2024-10_vendor_price_overrides.xlsx")
    return dst
