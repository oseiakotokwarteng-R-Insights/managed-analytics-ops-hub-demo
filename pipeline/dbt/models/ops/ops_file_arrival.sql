{{ config(materialized='table') }}
-- Every loaded file as an arrival of its stream. loaded_as_of is the nightly run that made it available.
select
    f.file_id, f.rel_path, f.table_name,
    case when f.table_name = 'wms_events' then 'wms:' || regexp_extract(f.rel_path, 'wms/(WH-0[0-9])/', 1) else f.table_name end as stream,
    f.arrival, f.loaded_ts, cast(f.loaded_ts as date) - 1 as loaded_as_of, f.rows_loaded, f.sha256, f.status
from {{ source('raw', '_load_files') }} f
where f.status in ('LOADED', 'RELOADED_CHANGED')
