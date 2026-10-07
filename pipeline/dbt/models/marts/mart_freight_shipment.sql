{{ config(materialized='table') }}
-- One row per delivered-or-moving shipment with its cost (suspect duplicate charge lines excluded and shown separately), transit time and whether it was slow
-- against the assumed service standard (seed ref.service_standards). Shipments with an impossible delivery time keep their cost but have no transit time.
with ch as (
    select shipment_key, round(sum(amount) filter (where not is_suspect_duplicate), 2) as cost, round(sum(amount) filter (where is_suspect_duplicate), 2) as duplicate_cost
    from {{ ref('fct_freight_charge') }} group by 1
),
units as (select order_no, sum(qty_shipped_units) as units from {{ ref('fct_order_line') }} where not is_duplicate and exclude_reason is null group by 1)
select s.carrier, s.shipment_key, s.doc_no, coalesce(s.direction, 'unmatched') as direction, s.origin_city, s.dest_city, s.origin_city || ' to ' || s.dest_city as lane,
       cast(s.pickup_ts_utc as date) as pickup_date, date_trunc('week', cast(s.pickup_ts_utc as date)) as pickup_week, s.weight_lb, s.pieces,
       case when not s.flag_delivery_time_invalid then date_diff('day', s.pickup_ts_utc, s.delivered_ts_utc) end as transit_days,
       case when not s.flag_delivery_time_invalid and s.delivered_ts_utc is not null then date_diff('day', s.pickup_ts_utc, s.delivered_ts_utc) > t.max_transit_days end as is_slow,
       coalesce(c.cost, 0) as cost, coalesce(c.duplicate_cost, 0) as duplicate_cost, u.units as order_units
from {{ ref('fct_shipment') }} s
left join ch c using (shipment_key)
left join {{ ref('service_standards') }} t on t.direction = coalesce(s.direction, 'outbound')
left join units u on u.order_no = s.doc_no and s.doc_no like 'SO-%'
