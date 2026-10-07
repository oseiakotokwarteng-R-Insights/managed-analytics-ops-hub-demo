-- Both carriers in one shape, before reference matching and cleaning.
select 'CARRIER_A' as carrier, a.bol_no as shipment_key, a.shipper_ref as ref_raw, a.origin_city, a.dest_city,
       a.weight_lb as weight_lb_reported, a.pieces as pieces_reported,
       (select min(event_ts_utc) from {{ ref('int_carrier_a__event') }} e where e.bol_no = a.bol_no and e.status = 'PICKUP') as pickup_ts_utc,
       (select max(event_ts_utc) from {{ ref('int_carrier_a__event') }} e where e.bol_no = a.bol_no and e.status = 'DELIVERED') as delivered_ts_raw
from {{ ref('int_carrier_a__latest') }} a
union all
select 'CARRIER_B', b.tracking_no, b.reference, b.origin_city, b.dest_city, b.weight_lb, b.pieces, b.ship_ts_utc,
       (select max(event_ts_utc) from {{ ref('stg_carrier_b__tracking') }} t where t.tracking_no = b.tracking_no and t.status = 'DELIVERED')
from {{ ref('stg_carrier_b__shipment') }} b
