{{ config(materialized='table') }}
-- Vendor delivery performance over the last 180 days of receipts: on time means received on or before the promised date.
select p.vendor_no, v.name as vendor_name, count(*) as lines_received,
       round(avg((p.received_date <= p.promised_date)::int), 8) as on_time_rate,
       round(avg(date_diff('day', p.promised_date, p.received_date)), 8) as avg_days_vs_promise,
       round(sum(p.qty_ordered * p.unit_cost), 2) as value_received
from {{ ref('fct_po_line') }} p left join {{ ref('dim_vendor') }} v on v.vendor_no = p.vendor_no
where p.received_date is not null and p.received_date > cast('{{ var("history_end") }}' as date) - 180
group by 1, 2
