{{ config(materialized='table') }}
-- Per SKU-warehouse-day over the last 150 days: how much stock is estimated on hand, how fast it sells, how much is promised in, and whether it will run out.
-- Demand is the average daily shipments of the previous 28 days; only reliable inbound counts (promised from today to 14 days out).
with win as (select cast('{{ var("history_end") }}' as date) as dend),
spine as (
    select m.item_no, m.wh_code, m.local_date as d, m.est_on_hand, m.confidence
    from {{ ref('mart_stock_daily') }} m, win where m.local_date > win.dend - 178
),
ship as (
    select item_no, wh_code, local_date as d, -sum(qty_delta) as units
    from {{ ref('fct_stock_movement') }} where movement_type = 'SHIPMENT' group by 1, 2, 3
),
dem as (
    select s.item_no, s.wh_code, s.d, s.est_on_hand, s.confidence,
           sum(coalesce(h.units, 0)) over w as units_28d
    from spine s left join ship h using (item_no, wh_code, d)
    window w as (partition by s.item_no, s.wh_code order by s.d rows between 28 preceding and 1 preceding)
),
po as (
    select p.item_no, p.wh_code, p.promised_date, p.qty_ordered, cast(g.d as date) as d
    from {{ ref('fct_po_line') }} p, win,
         unnest(generate_series(greatest(p.po_date, win.dend - 149), least(coalesce(p.received_date - 1, win.dend), win.dend), interval 1 day)) as g(d)
),
inb as (
    select item_no, wh_code, d, sum(qty_ordered) as inbound_qty, min(promised_date) as first_promised
    from po where promised_date between d and d + 14 group by 1, 2, 3
),
r as (
    select x.item_no, x.wh_code, x.d, x.est_on_hand, x.confidence, x.units_28d, x.units_28d / 28.0 as daily_rate,
           coalesce(i.inbound_qty, 0) as inbound_14d_qty, date_diff('day', x.d, i.first_promised) as first_inbound_in_days
    from dem x left join inb i using (item_no, wh_code, d), win where x.d > win.dend - 150
)
select r.*,
       case when daily_rate > 0 and est_on_hand > 0 then est_on_hand / daily_rate end as days_of_cover,
       case when units_28d < 3 then 'low_demand'
            when est_on_hand <= 0 then 'out_of_stock'
            when est_on_hand / daily_rate <= 14
                 and not (inbound_14d_qty > 0 and first_inbound_in_days <= est_on_hand / daily_rate and est_on_hand + inbound_14d_qty >= 14 * daily_rate) then 'at_risk'
            else 'ok' end as risk
from r
