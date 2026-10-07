{{ config(materialized='table') }}
-- How accurate the system book is, measured by the physical counts: per warehouse and month, the share of counted items where the book was exactly right,
-- and the net and absolute variance in units and dollars at standard cost. Only counts usable as anchors are included (bad sheets are quarantined).
select c.wh_code, date_trunc('month', c.count_date) as month, count(*) as items_counted,
       round(avg((c.counted_qty = c.book_before)::int), 8) as exact_rate,
       sum(c.counted_qty - c.book_before) as net_variance_units,
       round(sum((c.counted_qty - c.book_before) * s.std_cost), 2) as net_variance_value,
       round(sum(abs(c.counted_qty - c.book_before) * s.std_cost), 2) as abs_variance_value,
       count(*) filter (where c.counted_qty < c.book_before) as short_items,
       count(*) filter (where c.counted_qty > c.book_before) as over_items
from {{ ref('fct_count') }} c join {{ ref('dim_sku') }} s using (item_no)
where c.is_anchor
group by 1, 2
