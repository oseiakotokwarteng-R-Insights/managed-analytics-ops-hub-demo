-- Carrier B before and after the 2026-06-04 schema change, mapped to one shape per contract v1 / v2.
select
    tracking_no, reference,
    strptime(ship_ts_local, '%Y-%m-%d %H:%M:%S %z') as ship_ts_utc,
    coalesce(try_cast(weight_lb as double), try_cast(wt_lbs as double)) as weight_lb,
    try_cast(dim_weight as double) as dim_weight_lb,
    try_cast(pieces as integer) as pieces,
    coalesce(service_level, 'GROUND') as service_level,
    coalesce(delivery_type, case service when 'GND-RES' then 'RES' when 'GND-COM' then 'COM' end) as delivery_type,
    origin_city, dest_city, (wt_lbs is not null) as is_contract_v2, _file_id, _row_num
from {{ source('raw', 'carrier_b_shipments') }}
qualify row_number() over (partition by tracking_no order by _file_id desc, _row_num) = 1
