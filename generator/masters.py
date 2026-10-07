"""Master data for the synthetic universe: warehouses, SKUs (with lifecycle and alternate identifiers),
vendors, customers, and the business calendar. Deterministic for a given SEED."""
from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np

from . import config as C

BRANDS = ["Pro", "Max", "HD", "Select", "Standard", "Contractor", "Premier", "Value", "Elite", "Builder",
          "Prime", "Trade"]

DESC = [  # items, sizes, specs  (one entry per category, same order as config.CATEGORIES)
    (["Stud", "Dimensional Lumber", "Plywood Sheet", "OSB Sheet", "Treated Post", "Beam", "Joist", "Fence Board"],
     ["2x4x8", "2x4x10", "2x6x8", "2x6x12", "2x8x12", "4x4x8", "4x8 1/2in", "4x8 3/4in", "1x6x8", "2x10x12"],
     ["SPF #2", "Douglas Fir", "Pressure Treated", "KD Premium", "Select Structural", "Cedar"]),
    (["Architectural Shingle", "3-Tab Shingle", "Underlayment", "Ridge Cap", "Drip Edge", "Roofing Felt", "Flashing", "Roof Vent"],
     ["Bundle", "Roll 4ft", "10ft", "Square", "5in", "Roll 3ft", "12in"],
     ["Weathered Wood", "Charcoal", "Desert Tan", "Synthetic", "Galvanized", "Ice & Water"]),
    (["Batt Insulation", "Blown-In Insulation", "Foam Board", "Radiant Barrier", "Spray Foam Kit", "Pipe Wrap"],
     ["R-13", "R-19", "R-30", "R-38", "1in", "2in", "3.5in"],
     ["Faced", "Unfaced", "Kraft", "Fiberglass", "Mineral Wool", "Closed Cell"]),
    (["Drywall Sheet", "Joint Compound", "Drywall Tape", "Corner Bead", "Ceiling Tile", "Metal Track", "Metal Stud", "Texture Spray"],
     ["4x8 1/2in", "4x12 5/8in", "5 gal", "Roll 250ft", "2x4", "3-5/8in", "1-5/8in"],
     ["Standard", "Moisture Resistant", "Fire Rated", "Lightweight", "Acoustic", "All-Purpose"]),
    (["Copper Pipe", "PVC Pipe", "PEX Tubing", "Ball Valve", "Elbow Fitting", "Coupling", "Water Heater", "Faucet", "Drain Kit"],
     ["1/2in", "3/4in", "1in", "1-1/2in", "2in", "40 gal", "50 gal", "3in"],
     ["Type L", "Sch 40", "Lead-Free", "Brass", "Chrome", "Push-Fit"]),
    (["Romex Cable", "Outlet", "Switch", "Breaker", "Conduit", "Wire Nut", "Junction Box", "LED Fixture", "Panel"],
     ["12/2", "14/2", "10/3", "15A", "20A", "1/2in", "3/4in", "100A", "200A", "4in"],
     ["White", "Ivory", "GFCI", "AFCI", "Tamper Resistant", "EMT", "Grounded"]),
    (["Condenser", "Furnace Filter", "Thermostat", "Ductwork", "Flex Duct", "Register", "Coil", "Blower Motor"],
     ["14x20x1", "16x25x1", "20x25x4", "6in", "8in", "10in", "2 Ton", "3 Ton", "4 Ton"],
     ["Programmable", "Smart", "MERV 8", "MERV 11", "Insulated", "R6"]),
    (["Wood Screw", "Drywall Screw", "Framing Nail", "Anchor Bolt", "Hinge", "Bracket", "Washer", "Lag Screw", "Deck Screw", "Hanger"],
     ["#8 x 2in", "#10 x 3in", "16d", "8d", "1/2 x 6in", "3/8 x 4in", "3in", "4in", "2x4", "2x6"],
     ["Zinc", "Galvanized", "Stainless", "Coated", "Hot-Dip", "Black Oxide"]),
    (["Interior Paint", "Exterior Paint", "Primer", "Stain", "Sealant", "Caulk", "Roller Cover", "Brush", "Elastomeric Coating"],
     ["1 gal", "5 gal", "Quart", "10oz", "9in", "4in", "2in"],
     ["Flat White", "Satin Eggshell", "Semi-Gloss", "Desert Sand", "Clear", "Tintable", "Low-VOC"]),
    (["Portland Cement", "Concrete Mix", "Mortar Mix", "Rebar", "Block", "Paver", "Stucco Mix", "Wire Mesh", "Gravel Bag"],
     ["80lb", "60lb", "94lb", "#4 x 20ft", "#3 x 10ft", "8x8x16", "12x12", "6x6", "50lb"],
     ["Type I/II", "High Early", "Fiber Reinforced", "Standard", "Heavy Duty", "Gray"]),
    (["Laminate Flooring", "Vinyl Plank", "Ceramic Tile", "Underlayment", "Transition Strip", "Grout", "Thinset", "Baseboard"],
     ["12mm", "6mm", "12x24", "18x18", "Roll 100sqft", "25lb", "50lb", "3.25in"],
     ["Oak", "Gray Oak", "Desert Stone", "Matte", "Waterproof", "Sanded"]),
    (["Cordless Drill", "Circular Saw", "Tape Measure", "Work Gloves", "Safety Glasses", "Hard Hat", "Level", "Utility Knife", "Respirator"],
     ["18V", "20V", "25ft", "30ft", "2ft", "4ft", "Large", "Medium", "XL"],
     ["Kit", "Bare Tool", "Impact Rated", "Anti-Fog", "Cut Resistant", "Vented"]),
]

CAT_CODES = ["LF", "RF", "IN", "DW", "PB", "EL", "HV", "FH", "PT", "CM", "FL", "TS"]

CUST_ADJ = ["Desert", "Mesa", "Canyon", "Red Rock", "Copper", "Saguaro", "High Desert", "Sunbelt", "Ironwood", "Mojave",
            "Sonoran", "Pinnacle", "Summit", "Cactus Valley", "Black Mesa", "Painted Sky", "Juniper", "Mesquite", "Lone Pine",
            "Rio Verde", "Silver State", "Four Corners", "Sandstone", "Tumbleweed", "Blue Agave", "Chaparral"]
CUST_NOUN = {
    "Contractor": ["Builders", "Construction", "Roofing", "Remodeling", "Plumbing", "Electric", "Concrete", "Framing", "Homes",
                   "Mechanical", "Contracting", "Restoration", "Drywall", "Flooring"],
    "Retail": ["Hardware", "Home Center", "Lumber & Supply", "Do-It Center", "Farm & Home"],
    "Commercial": ["Property Management", "Facilities Group", "Hospitality Group", "Maintenance Services", "Development Partners"],
}
CUST_SUFFIX = ["LLC", "Inc", "Co", "& Sons", "Group", "Corp", "Partners"]
REGION_CITIES = {
    1: ["Phoenix, AZ", "Mesa, AZ", "Scottsdale, AZ", "Glendale, AZ", "Chandler, AZ", "Tempe, AZ", "Peoria, AZ", "Gilbert, AZ"],
    2: ["Tucson, AZ", "Marana, AZ", "Oro Valley, AZ", "Sierra Vista, AZ", "Green Valley, AZ"],
    3: ["Flagstaff, AZ", "Sedona, AZ", "Prescott, AZ", "Cottonwood, AZ", "Williams, AZ"],
    4: ["Las Vegas, NV", "Henderson, NV", "North Las Vegas, NV", "Boulder City, NV", "Pahrump, NV"],
    5: ["Albuquerque, NM", "Rio Rancho, NM", "Santa Fe, NM", "Los Lunas, NM", "Bernalillo, NM"],
    6: ["El Paso, TX", "Horizon City, TX", "Socorro, TX", "Las Cruces, NM", "Canutillo, TX"],
}
VEND_WORD = ["Atlas", "Keystone", "Ridgeline", "Bluewater", "Granite", "Evergreen", "Redwood", "Northstar", "Ironclad",
             "Summit", "Harbor", "Cornerstone", "Pioneer", "Liberty", "Heritage", "Apex", "Vanguard", "Meridian", "Falcon",
             "Sterling", "Cascade", "Bedrock", "Timberline", "Prairie", "Lakeshore", "Westfield", "Eastgate", "Hallmark"]
VEND_SUFFIX = ["Manufacturing", "Supply", "Industries", "Products", "Materials", "Distribution", "Mills", "Works"]


def us_holidays(year: int) -> dict[date, str]:
    def nth_weekday(month, weekday, n):
        d = date(year, month, 1)
        shift = (weekday - d.weekday()) % 7
        return d + timedelta(days=shift + 7 * (n - 1))

    last_mon_may = max(d for d in (date(year, 5, x) for x in range(25, 32)) if d.weekday() == 0)
    thanksgiving = nth_weekday(11, 3, 4)
    return {
        date(year, 1, 1): "New Year's Day",
        last_mon_may: "Memorial Day",
        date(year, 7, 4): "Independence Day",
        nth_weekday(9, 0, 1): "Labor Day",
        thanksgiving: "Thanksgiving",
        thanksgiving + timedelta(days=1): "Day after Thanksgiving",
        date(year, 12, 25): "Christmas Day",
    }


def build_calendar(start: date, end: date):
    days = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(days)]
    hol = {}
    for y in range(start.year, end.year + 1):
        hol.update(us_holidays(y))
    dow = np.array([d.weekday() for d in dates])
    is_hol = np.array([d in hol for d in dates])
    is_open = (dow != 6) & ~is_hol
    is_recv = (dow < 5) & ~is_hol
    pidx = np.ones(days)
    for step in C.PRICE_STEPS:
        pidx[np.array([d >= step for d in dates])] *= 1 + C.PRICE_STEP_PCT
    ordinals = np.array([d.toordinal() for d in dates])
    return SimpleNamespace(start=start, dates=dates, ordinals=ordinals, dow=dow, is_hol=is_hol, is_open=is_open,
                           is_recv=is_recv, price_index=pidx, holiday_name=[hol.get(d, "") for d in dates],
                           base_ord=start.toordinal())


def _unique_text(rng, make, used, tries=60):
    for _ in range(tries):
        t = make()
        if t not in used:
            used.add(t)
            return t
    t = make() + f" {len(used)}"
    used.add(t)
    return t


def build_masters(seed: int = C.SEED) -> SimpleNamespace:
    rng = np.random.default_rng([seed, 0])
    M = SimpleNamespace()
    M.cal = build_calendar(C.WARMUP_START, date(2028, 12, 31))

    # ---- warehouses
    W = C.WAREHOUSES
    M.n_wh = len(W)
    M.wh_id = np.array([w[0] for w in W])
    M.wh_code = [w[1] for w in W]
    M.wh_name = [w[2] for w in W]
    M.wh_city = [w[3] for w in W]
    M.wh_tz = [w[4] for w in W]
    M.wh_is_hub = np.array([w[5] for w in W])
    M.wh_wms = np.array([w[6] for w in W])
    M.wh_share = np.array([w[7] for w in W])
    M.wh_assort = np.array([w[8] for w in W])
    M.wh_transfer_days = np.array([w[9] for w in W])

    # ---- categories
    CT = C.CATEGORIES
    M.n_cat = len(CT)
    M.cat_name = [c[0] for c in CT]
    M.cat_season_amp = np.array([c[7] for c in CT])
    M.cat_season_peak = np.array([c[8] for c in CT])
    M.cat_season_harm = np.array([c[9] for c in CT])
    doy = np.arange(1, 368)
    M.season = np.stack([1 + M.cat_season_amp[c] * np.cos(M.cat_season_harm[c] * 2 * np.pi * (doy - M.cat_season_peak[c]) / 365.0)
                         for c in range(M.n_cat)])

    # ---- SKUs: [0, n_orig) originals, then successors, then new launches
    n_orig = C.N_ACTIVE_SKUS_END + C.N_SUPERSEDED + C.N_END_OF_LIFE - C.N_SUPERSEDED - C.N_NEW_SKUS
    n_succ, n_new = C.N_SUPERSEDED, C.N_NEW_SKUS
    n = n_orig + n_succ + n_new
    M.n_sku, M.n_orig, M.n_succ = n, n_orig, n_succ
    shares = np.array([c[1] for c in CT])
    cat = np.empty(n, dtype=int)
    cat[:n_orig] = rng.choice(M.n_cat, size=n_orig, p=shares)

    old_idx = rng.choice(n_orig, size=n_succ + C.N_END_OF_LIFE, replace=False)
    sup_old, eol = old_idx[:n_succ], old_idx[n_succ:]
    cat[n_orig:n_orig + n_succ] = cat[sup_old]
    cat[n_orig + n_succ:] = rng.choice(M.n_cat, size=n_new, p=shares)
    M.sku_cat = cat

    base = rng.lognormal(0, 1.25, size=n)
    base[n_orig:n_orig + n_succ] = base[sup_old]
    M.sku_base_lines = base

    def cat_param(idx, col):
        return np.array([CT[c][col] for c in cat[idx]])

    allidx = np.arange(n)
    price = cat_param(allidx, 2) * rng.lognormal(0, 1, size=n) ** (cat_param(allidx, 3))
    price = np.clip(price, 0.6, None)
    price[n_orig:n_orig + n_succ] = price[sup_old] * rng.uniform(1.0, 1.08, size=n_succ)
    margin = cat_param(allidx, 10) * rng.uniform(0.85, 1.15, size=n)
    M.sku_price0 = price
    M.sku_cost0 = price * (1 - margin)
    wt = cat_param(allidx, 4) * rng.lognormal(0, 0.4, size=n)
    mq = np.clip(cat_param(allidx, 5) * rng.lognormal(0, 0.3, size=n), 1, None)
    cp = cat_param(allidx, 6).astype(int)
    for arr in (wt, mq, cp):
        arr[n_orig:n_orig + n_succ] = arr[sup_old]
    M.sku_weight, M.sku_mean_qty, M.sku_case_pack = wt, mq, cp

    # lifecycle (ordinals)
    NEVER, ALWAYS = 10 ** 9, -10 ** 6
    intro = np.full(n, ALWAYS, dtype=np.int64)
    disc = np.full(n, NEVER, dtype=np.int64)
    ramp = np.full(n, 30, dtype=np.int64)
    fade = np.full(n, 30, dtype=np.int64)
    lo, hi = date(2024, 12, 1).toordinal(), date(2026, 7, 15).toordinal()
    disc[sup_old] = rng.integers(lo, hi, size=n_succ)
    disc[eol] = rng.integers(lo, hi, size=C.N_END_OF_LIFE)
    fade[eol] = 60
    intro[n_orig:n_orig + n_succ] = disc[sup_old]
    nlo, nhi = date(2024, 11, 15).toordinal(), date(2026, 8, 15).toordinal()
    intro[n_orig + n_succ:] = rng.integers(nlo, nhi, size=n_new)
    ramp[n_orig + n_succ:] = 45
    M.sku_intro, M.sku_disc, M.sku_ramp, M.sku_fade = intro, disc, ramp, fade
    successor = np.full(n, -1, dtype=int)
    successor[sup_old] = np.arange(n_orig, n_orig + n_succ)
    M.sku_successor = successor
    M.sku_kind = np.array(["continuing"] * n, dtype=object)
    M.sku_kind[sup_old] = "superseded"
    M.sku_kind[eol] = "end_of_life"
    M.sku_kind[n_orig:n_orig + n_succ] = "successor"
    M.sku_kind[n_orig + n_succ:] = "new_launch"

    # ABC class by cumulative volume
    order = np.argsort(-base)
    cum = np.cumsum(base[order]) / base.sum()
    klass = np.empty(n, dtype="<U1")
    klass[order] = np.where(cum <= 0.70, "A", np.where(cum <= 0.90, "B", "C"))
    klass[n_orig:n_orig + n_succ] = klass[sup_old]
    M.sku_class = klass

    # codes and alternate identifiers
    nums = np.empty(n, dtype=int)
    revs = np.empty(n, dtype="<U1")
    used_nums = set()
    for i in range(n_orig):
        while True:
            v = 10000 + int(cat[i]) * 8000 + int(rng.integers(0, 7999))
            if v not in used_nums:
                used_nums.add(v)
                break
        nums[i] = v
        revs[i] = rng.choice(["A", "B", "C"], p=[0.8, 0.15, 0.05])
    for k, o in enumerate(sup_old):
        i = n_orig + k
        if rng.random() < 0.38:
            nums[i] = nums[o]
            revs[i] = chr(ord(revs[o]) + 1)
        else:
            while True:
                v = 10000 + int(cat[i]) * 8000 + int(rng.integers(0, 7999))
                if v not in used_nums:
                    used_nums.add(v)
                    break
            nums[i], revs[i] = v, "A"
    for i in range(n_orig + n_succ, n):
        while True:
            v = 10000 + int(cat[i]) * 8000 + int(rng.integers(0, 7999))
            if v not in used_nums:
                used_nums.add(v)
                break
        nums[i], revs[i] = v, "A"
    M.sku_code = [f"NF-{nums[i]:05d}-{revs[i]}" for i in range(n)]
    M.sku_legacy_code = [f"{CAT_CODES[cat[i]]}{nums[i]:05d}{chr(65 + nums[i] % 26)}" for i in range(n)]
    M.sku_wms_item_id = rng.permutation(np.arange(100000, 100000 + n * 3))[:n]
    used_desc: set = set()
    descs = []
    for i in range(n):
        items, sizes, specs = DESC[cat[i]]
        descs.append(_unique_text(
            rng, lambda: f"{rng.choice(BRANDS)} {rng.choice(items)} {rng.choice(sizes)} {rng.choice(specs)}", used_desc))
    for k, o in enumerate(sup_old):  # successors read like their predecessor, as in real catalogs
        if rng.random() < 0.7:
            descs[n_orig + k] = descs[o] + " II"
    M.sku_desc = descs

    # ---- vendors
    nv = C.N_VENDORS
    M.n_vend = nv
    v_cats = []
    for v in range(nv):
        k = int(rng.choice([1, 2, 3], p=[0.55, 0.33, 0.12]))
        v_cats.append(set(rng.choice(M.n_cat, size=k, replace=False).tolist()))
    for c in range(M.n_cat):  # every category must have vendors
        have = [v for v in range(nv) if c in v_cats[v]]
        while len(have) < 8:
            v = int(rng.integers(0, nv))
            v_cats[v].add(c)
            have = [v for v in range(nv) if c in v_cats[v]]
    M.vend_cats = v_cats
    imp = rng.random(nv) < 0.10
    M.vend_import = imp
    ql = np.where(imp, np.clip(rng.lognormal(np.log(40), 0.25, nv), 28, 70), np.clip(rng.lognormal(np.log(10), 0.5, nv), 3, 35))
    M.vend_quoted_lt = np.round(ql).astype(int)
    M.vend_late_prob = rng.uniform(0.08, 0.35, nv)
    M.vend_dist_miles = np.where(imp, rng.uniform(1500, 2400, nv), np.clip(rng.lognormal(np.log(450), 0.8, nv), 20, 1800))
    M.vend_order_days = [sorted(rng.choice(5, size=int(rng.choice([1, 2], p=[0.55, 0.45])), replace=False).tolist()) for _ in range(nv)]
    M.vend_cycle = rng.choice([1, 2, 4], size=nv, p=[0.20, 0.40, 0.40])  # buy cycle in weeks
    M.vend_offset = np.array([int(rng.integers(0, c)) for c in M.vend_cycle])
    M.vend_dow_mask = np.zeros((nv, 7), dtype=bool)
    for v in range(nv):
        M.vend_dow_mask[v, M.vend_order_days[v]] = True
    used_v: set = set()
    M.vend_name = [_unique_text(rng, lambda: f"{rng.choice(VEND_WORD)} {rng.choice(M.cat_name).split(' ')[0]} {rng.choice(VEND_SUFFIX)}", used_v)
                   for _ in range(nv)]
    sku_vendor = np.empty(n, dtype=int)
    for i in range(n_orig):
        cands = [v for v in range(nv) if cat[i] in v_cats[v]]
        sku_vendor[i] = cands[int(rng.integers(0, len(cands)))]
    sku_vendor[n_orig:n_orig + n_succ] = sku_vendor[sup_old]
    for i in range(n_orig + n_succ, n):
        cands = [v for v in range(nv) if cat[i] in v_cats[v]]
        sku_vendor[i] = cands[int(rng.integers(0, len(cands)))]
    M.sku_vendor = sku_vendor

    # ---- pairs (SKU x warehouse)
    stocked = np.zeros((n, M.n_wh), dtype=bool)
    stocked[:, 0] = True
    for i in range(n):
        if n_orig <= i < n_orig + n_succ:
            stocked[i] = stocked[sup_old[i - n_orig]]
            continue
        p = np.clip(C.CLASS_STOCK_PROB[klass[i]] * M.wh_assort, 0, 1)
        stocked[i, 1:] = rng.random(M.n_wh - 1) < p[1:]
    sku_i, wh_i = np.nonzero(stocked)
    M.n_pair = len(sku_i)
    M.pair_sku, M.pair_wh = sku_i, wh_i
    share_sum = (stocked * M.wh_share[None, :]).sum(axis=1)
    M.pair_lam_base = base[sku_i] * M.wh_share[wh_i] / share_sum[sku_i]

    # ---- scenario selections
    p_s1 = np.nonzero((M.pair_wh == C.S1_WH - 1) & np.isin(klass[M.pair_sku], ["A", "B"]) & (M.sku_kind[M.pair_sku] == "continuing"))[0]
    M.s1_pairs = np.sort(rng.choice(p_s1, size=min(C.S1_N_SKUS, len(p_s1)), replace=False))
    roof = M.sku_cat == 1
    p_s5 = np.nonzero((M.pair_wh == C.S5_WH - 1) & roof[M.pair_sku] & (M.sku_kind[M.pair_sku] == "continuing"))[0]
    M.s5_pairs = np.sort(rng.choice(p_s5, size=min(C.S5_N_SKUS, len(p_s5)), replace=False))

    # ---- customers
    nc = C.N_CUSTOMERS
    M.n_cust = nc
    ctype = rng.choice(len(C.CUSTOMER_TYPES), size=nc, p=C.CUSTOMER_TYPE_SHARE)
    M.cust_type = ctype
    M.cust_size = rng.lognormal(0, 1.0, nc)
    M.cust_wh = rng.choice(M.n_wh, size=nc, p=M.wh_share / M.wh_share.sum())
    M.cust_dist_miles = np.clip(rng.lognormal(np.log(22), 0.95, nc), 2, 420)
    disc_lo = np.array([C.CUSTOMER_DISCOUNT[C.CUSTOMER_TYPES[t]][0] for t in ctype])
    disc_hi = np.array([C.CUSTOMER_DISCOUNT[C.CUSTOMER_TYPES[t]][1] for t in ctype])
    M.cust_discount = np.round(rng.uniform(disc_lo, disc_hi), 3)
    M.cust_willcall = np.array([C.WILLCALL_PROB[C.CUSTOMER_TYPES[t]] for t in ctype])
    M.cust_terms = np.where(ctype == 1, "COD", np.where(rng.random(nc) < 0.7, "Net 30", "Net 15"))
    wo = date(2024, 8, 2).toordinal()
    start_ord = np.full(nc, -10 ** 6, dtype=np.int64)
    end_ord = np.full(nc, 10 ** 9, dtype=np.int64)
    late = rng.random(nc) < 0.15
    start_ord[late] = rng.integers(C.WINDOW_START.toordinal(), C.HISTORY_END.toordinal() - 30, late.sum())
    gone = (~late) & (rng.random(nc) < 0.08)
    end_ord[gone] = rng.integers(C.WINDOW_START.toordinal() + 90, C.HISTORY_END.toordinal(), gone.sum())
    M.cust_start, M.cust_end = start_ord, end_ord
    used_c: set = set()
    names, cities = [], []
    for j in range(nc):
        t = C.CUSTOMER_TYPES[ctype[j]]
        names.append(_unique_text(rng, lambda: f"{rng.choice(CUST_ADJ)} {rng.choice(CUST_NOUN[t])} {rng.choice(CUST_SUFFIX)}", used_c))
        cities.append(rng.choice(REGION_CITIES[int(M.cust_wh[j]) + 1]))
    M.cust_name, M.cust_city = names, cities

    # customer-type affinity by category (probability of the type given first line's category)
    aff = np.ones((M.n_cat, len(C.CUSTOMER_TYPES)))
    for ti, tname in enumerate(C.CUSTOMER_TYPES):
        for ci in C.CUSTOMER_TYPE_FAVORED_CATS[tname]:
            aff[ci, ti] = 3.0
    aff *= np.array(C.CUSTOMER_TYPE_SHARE)[None, :]
    M.type_given_cat_cum = np.cumsum(aff / aff.sum(axis=1, keepdims=True), axis=1)

    # ---- hub pair lookup (every SKU is stocked at the hub)
    hub_pair = np.full(n, -1, dtype=int)
    hp = np.nonzero(M.pair_wh == 0)[0]
    hub_pair[M.pair_sku[hp]] = hp
    M.hub_pair_of_sku = hub_pair

    # ---- timezone offsets (seconds east of UTC) per calendar day x warehouse, measured at local noon
    from zoneinfo import ZoneInfo
    from datetime import datetime, timezone
    off = np.zeros((len(M.cal.dates), M.n_wh), dtype=np.int64)
    zi = [ZoneInfo(t) for t in M.wh_tz]
    for di, d in enumerate(M.cal.dates):
        for w in range(M.n_wh):
            off[di, w] = int(datetime(d.year, d.month, d.day, 12, tzinfo=zi[w]).utcoffset().total_seconds())
    M.utc_offset_s = off
    return M
