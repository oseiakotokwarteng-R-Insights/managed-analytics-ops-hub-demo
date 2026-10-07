-- Vendor price overrides typed twice with different prices for the same vendor, item and effective date (defect X6).
-- Documented rule: the later entry is the price in force; the conflict goes to purchasing so someone confirms it.
with g as (
    select vendor_name, item_no, effective_date, count(distinct override_cost) as n_prices
    from {{ ref('stg_sheets__price_row') }} group by 1, 2, 3 having count(distinct override_cost) > 1
)
select r.rel_path || '|' || cast(r.sheet_row as varchar) as row_key, r.vendor_name, r.item_no, r.effective_date, r.override_cost, r.entered_on, r.entered_by, g.n_prices,
       row_number() over (partition by r.vendor_name, r.item_no, r.effective_date order by r.entered_on desc, r.rel_path desc, r.sheet_row desc) = 1 as is_price_in_force
from {{ ref('stg_sheets__price_row') }} r join g using (vendor_name, item_no, effective_date)
