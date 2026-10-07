{{ config(materialized='table') }}
-- WMS events, de-duplicated on event_id (at-least-once delivery re-sends the same event), typed, with the local business date.
with ranked as (
    select e.*,
           row_number() over (partition by event_id order by published_at, _file_id, _row_num) as rn,
           count(*) over (partition by event_id) as n_copies
    from {{ source('raw', 'wms_events') }} e
)
select
    r.event_id, r.warehouse                                          as wh_code,
    r.event_type,
    cast(r.event_ts as timestamptz)                                  as event_ts_utc,
    cast(r.published_at as timestamptz)                              as published_ts_utc,
    cast(r.item_id as bigint)                                        as item_id,
    cast(r.quantity as integer)                                      as quantity,
    r.direction,
    {{ canonical_bin('r.bin') }}                                     as bin,
    r.ref_type, r.ref_no, r.reason, r.n_copies,
    cast(timezone(w.timezone, cast(r.event_ts as timestamptz)) as date) as local_date
from ranked r
join {{ ref('stg_erp__warehouse') }} w on w.wh_code = r.warehouse
where r.rn = 1
