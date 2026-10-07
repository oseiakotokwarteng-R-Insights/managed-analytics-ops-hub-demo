{{ config(materialized='table') }}
-- Lanes over the last 90 days: where the freight money goes, what it costs per 100 lb, and where shipments run slow.
select carrier, lane, direction, count(*) as shipments, round(sum(cost), 2) as cost, round(sum(weight_lb), 3) as weight_lb, round(sum(cost) / nullif(sum(weight_lb) / 100.0, 0), 6) as cost_per_100lb,
       median(transit_days) as median_transit_days, count(*) filter (where is_slow) as slow_shipments, count(*) filter (where transit_days is not null) as timed_shipments
from {{ ref('mart_freight_shipment') }}
where pickup_date > cast('{{ var("history_end") }}' as date) - 93 and pickup_date <= cast('{{ var("history_end") }}' as date) - 3  -- invoiced shipments only
group by 1, 2, 3
