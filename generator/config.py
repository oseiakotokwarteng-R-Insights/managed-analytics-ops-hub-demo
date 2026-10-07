"""Constants and parameters for the System 1 synthetic universe (see docs/SPEC.md)."""
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTH_DIR = Path(os.environ.get("OPS_HUB_TRUTH_DIR", ROOT / "truth"))

SEED = 20261004

WARMUP_START = date(2024, 8, 2)
WINDOW_START = date(2024, 10, 1)
HISTORY_END = date(2026, 9, 30)
# How far the simulation and the source builders run. Masters, calibration and scenarios are tied to HISTORY_END, so extending the horizon only adds days;
# every day is drawn from its own keyed random stream, so the history itself does not change.
HORIZON_END = date.fromisoformat(os.environ.get("OPS_HUB_HORIZON_END", HISTORY_END.isoformat()))

TARGET_LINES_WINDOW = 612_000
TARGET_ANNUAL_REVENUE = 48_000_000
EXPECTED_FILL = 0.965

N_ACTIVE_SKUS_END = 2500
N_SUPERSEDED = 220
N_END_OF_LIFE = 80
N_NEW_SKUS = 150
N_CUSTOMERS = 1600
N_VENDORS = 140

ANNUAL_GROWTH = 0.06
DOW_FACTOR = {0: 1.0, 1: 1.05, 2: 1.05, 3: 1.0, 4: 0.95, 5: 0.35, 6: 0.0}
MEAN_LINES_PER_ORDER = 3.4
EWMA_ALPHA = 0.07
SHRINK_DAILY_PROB = 0.00025

# id, code, name, city, tz, is_hub, wms_covered, volume_share, assortment_factor, transfer_days_from_hub
WAREHOUSES = [
    (1, "WH-01", "Phoenix", "Phoenix, AZ", "America/Phoenix", True, True, 0.30, 1.00, 0),
    (2, "WH-02", "Tucson", "Tucson, AZ", "America/Phoenix", False, True, 0.15, 0.95, 1),
    (3, "WH-03", "Flagstaff", "Flagstaff, AZ", "America/Phoenix", False, True, 0.08, 0.75, 2),
    (4, "WH-04", "Las Vegas", "Las Vegas, NV", "America/Los_Angeles", False, True, 0.20, 1.00, 2),
    (5, "WH-05", "Albuquerque", "Albuquerque, NM", "America/Denver", False, False, 0.12, 0.90, 3),
    (6, "WH-06", "El Paso", "El Paso, TX", "America/Denver", False, True, 0.15, 0.95, 3),
]

# name, sku_share, price_median, price_sigma, weight_lb, mean_qty, case_pack, season_amp, season_peak_doy, harmonics, margin
CATEGORIES = [
    ("Lumber & Framing", 0.12, 14, 0.7, 9.0, 24, 1, 0.15, 165, 1, 0.22),
    ("Roofing", 0.08, 32, 0.6, 40.0, 12, 3, 0.45, 200, 1, 0.28),
    ("Insulation", 0.06, 28, 0.5, 18.0, 10, 4, 0.35, 15, 1, 0.30),
    ("Drywall & Ceiling", 0.07, 16, 0.5, 55.0, 14, 1, 0.12, 120, 1, 0.26),
    ("Plumbing", 0.13, 11, 0.9, 2.0, 8, 10, 0.08, 30, 1, 0.34),
    ("Electrical", 0.13, 8, 1.0, 1.0, 12, 25, 0.05, 150, 1, 0.36),
    ("HVAC", 0.06, 45, 0.9, 12.0, 3, 1, 0.35, 200, 2, 0.30),
    ("Fasteners & Hardware", 0.14, 6, 0.8, 0.6, 20, 50, 0.10, 150, 1, 0.38),
    ("Paint & Coatings", 0.08, 30, 0.6, 11.0, 6, 4, 0.30, 130, 1, 0.33),
    ("Concrete & Masonry", 0.05, 9, 0.6, 60.0, 20, 1, 0.40, 185, 1, 0.24),
    ("Flooring", 0.04, 38, 0.8, 30.0, 8, 1, 0.15, 110, 1, 0.32),
    ("Tools & Safety", 0.04, 22, 0.9, 3.0, 3, 6, 0.10, 150, 1, 0.35),
]

CUSTOMER_TYPES = ["Contractor", "Retail", "Commercial"]
CUSTOMER_TYPE_SHARE = [0.60, 0.25, 0.15]
CUSTOMER_TYPE_FAVORED_CATS = {
    "Contractor": [0, 1, 2, 3, 9, 7],
    "Retail": [8, 7, 11, 4, 5, 10],
    "Commercial": [6, 5, 4, 9],
}
CUSTOMER_DISCOUNT = {"Contractor": (0.08, 0.18), "Retail": (0.0, 0.05), "Commercial": (0.10, 0.15)}
WILLCALL_PROB = {"Contractor": 0.35, "Retail": 0.50, "Commercial": 0.10}

CLASS_STOCK_PROB = {"A": 1.0, "B": 0.9, "C": 0.6}
CLASS_Z = {"A": 1.65, "B": 1.28, "C": 0.84}
CLASS_COVER_DAYS = {"A": 14, "B": 20, "C": 30}

PRICE_STEPS = [date(2025, 1, 1), date(2025, 7, 1), date(2026, 1, 1), date(2026, 7, 1)]
PRICE_STEP_PCT = 0.015

# Scenarios simulated in truth (S2, S3, S4 are source-level and handled in Phase 2)
S1_START = date(2026, 3, 10)
S1_DISCOVERED = date(2026, 5, 18)
S1_N_SKUS = 85
S1_WH = 5
S5_START = date(2026, 6, 1)
S5_END = date(2026, 7, 31)
S5_WH = 4
S5_N_SKUS = 30
S5_MULT = 2.4
S3_START = date(2026, 1, 21)
S3_END = date(2026, 1, 23)
S3_WH = 3
S2_DATE = date(2026, 6, 4)
S4_DUPLICATE_BILLING_RATE = 0.010  # share of Carrier A shipments with a duplicated charge line

# Incidents scheduled in the live future (source-level, same mechanics as S3 and W4, later in time)
L1_WH, L1_START, L1_END = 2, date(2026, 11, 17), date(2026, 11, 19)  # WMS outage at Tucson, three days
L2_WH, L2_DATE = 4, date(2027, 1, 19)  # Las Vegas relabels its bins
