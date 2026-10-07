select distinct tracking_no, strptime(event_ts_local, '%Y-%m-%d %H:%M:%S %z') as event_ts_utc, status, location
from {{ source('raw', 'carrier_b_tracking') }}
