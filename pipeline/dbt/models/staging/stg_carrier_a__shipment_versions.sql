-- Carrier A emits the non-standard JSON token NaN for unknown cities; normalise to null before parsing.
select
    bol_no, pro_no, shipper_ref, service,
    json_extract_string(replace(origin, 'NaN', 'null'), '$.city')       as origin_city,
    json_extract_string(replace(destination, 'NaN', 'null'), '$.city')  as dest_city,
    try_cast(pieces as integer) as pieces, try_cast(weight_lb as double) as weight_lb, status,
    replace(coalesce(events, '[]'), 'NaN', 'null')  as events_json,
    replace(coalesce(charges, '[]'), 'NaN', 'null') as charges_json,
    json_array_length(replace(coalesce(events, '[]'), 'NaN', 'null')) as n_events,
    (charges is not null) as has_charges, _file_id, _row_num
from {{ source('raw', 'carrier_a_shipments') }}
