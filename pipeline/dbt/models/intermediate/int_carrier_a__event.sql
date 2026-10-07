select bol_no, to_timestamp(e.ts_ms / 1000.0) as event_ts_utc, e.status, e.location
from (
    select bol_no, unnest(from_json(events_json, '[{"ts_ms":"BIGINT","status":"VARCHAR","location":"VARCHAR"}]')) as e
    from {{ ref('int_carrier_a__latest') }}
)
