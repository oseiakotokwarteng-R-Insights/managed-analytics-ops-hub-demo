"""Pipeline paths. The pipeline reads ONLY the source systems' files under sources/ -- never the generator's hidden answer key."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = Path(os.environ.get("OPS_HUB_SOURCES", ROOT / "sources"))
WAREHOUSE = Path(os.environ.get("OPS_HUB_DB", ROOT / "warehouse" / "ops_hub.duckdb"))
CONTRACTS = ROOT / "pipeline" / "contracts" / "contracts.json"
