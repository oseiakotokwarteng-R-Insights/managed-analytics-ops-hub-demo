{{ config(materialized='table') }}
-- Freight by week, carrier and direction: volume, cost, cost per 100 lb, cost per order and per unit shipped (outbound orders), slow rate, and recoverable duplicate charges.
select carrier, direction, pickup_week as week, count(*) as shipments, round(sum(weight_lb), 3) as weight_lb, round(sum(cost), 2) as cost, round(sum(duplicate_cost), 2) as duplicate_cost,
       round(sum(cost) / nullif(sum(weight_lb) / 100.0, 0), 6) as cost_per_100lb,
       count(*) filter (where doc_no like 'SO-%') as order_shipments,
       round(sum(cost) filter (where doc_no like 'SO-%') / nullif(count(distinct doc_no) filter (where doc_no like 'SO-%'), 0), 6) as cost_per_order,
       round(sum(cost) filter (where doc_no like 'SO-%') / nullif(sum(order_units) filter (where doc_no like 'SO-%'), 0), 6) as cost_per_unit,
       count(*) filter (where transit_days is not null) as timed_shipments, count(*) filter (where is_slow) as slow_shipments
from {{ ref('mart_freight_shipment') }}
-- the last 3 days are left out: carriers invoice on delivery, so those shipments have no charges yet and would drag every cost figure down
where pickup_date <= cast('{{ var("history_end") }}' as date) - 3
group by 1, 2, 3
