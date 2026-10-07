{{ config(materialized='table') }}
-- The answer to "what can I promise and what is about to run out" for the latest day: one row per SKU and warehouse.
with win as (select cast('{{ var("history_end") }}' as date) as dend),
cur as (select r.* from {{ ref('mart_stock_risk_daily') }} r, win where r.d = win.dend),
mm as (select m.item_no, m.wh_code, m.book_recorded_qty, m.last_anchor_date, m.days_since_anchor from {{ ref('mart_stock_daily') }} m, win where m.local_date = win.dend),
committed as (
    select item_no, wh_code, sum(qty_ordered_units - coalesce(qty_shipped_units, 0)) as committed_units
    from {{ ref('fct_order_line') }}
    where not is_duplicate and exclude_reason is null and status in ('OPEN', 'PARTIAL', 'BACKORDER') group by 1, 2
),
donor as (
    select item_no, wh_code as donor_wh, est_on_hand - ceil(45 * daily_rate) as surplus
    from cur where confidence <> 'suspect' and est_on_hand - ceil(45 * daily_rate) >= 10
),
cand as (
    select c.item_no, c.wh_code, d.donor_wh, d.surplus,
           row_number() over (partition by c.item_no, c.wh_code order by d.surplus desc, d.donor_wh) as rk
    from cur c join donor d on d.item_no = c.item_no and d.donor_wh <> c.wh_code
    where c.risk in ('at_risk', 'out_of_stock')
)
select c.item_no, s.description, s.category, c.wh_code, c.d as as_of, c.est_on_hand, c.confidence, mm.book_recorded_qty, c.est_on_hand - mm.book_recorded_qty as est_minus_recorded,
       mm.last_anchor_date, mm.days_since_anchor, coalesce(k.committed_units, 0) as committed_units, c.est_on_hand - coalesce(k.committed_units, 0) as available_to_promise,
       c.daily_rate, c.days_of_cover, c.inbound_14d_qty, c.first_inbound_in_days, c.risk, s.std_cost, s.list_price,
       x.donor_wh as transfer_from, cast(least(x.surplus, ceil(30 * c.daily_rate)) as integer) as transfer_qty
from cur c join {{ ref('dim_sku') }} s using (item_no) join mm using (item_no, wh_code)
left join committed k using (item_no, wh_code)
left join cand x on x.item_no = c.item_no and x.wh_code = c.wh_code and x.rk = 1
