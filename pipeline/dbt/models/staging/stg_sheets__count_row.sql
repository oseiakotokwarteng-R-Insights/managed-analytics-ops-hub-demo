{{ config(materialized='table') }}
-- Cycle-count sheets. Structure is interpreted here: find the header row (names vary by branch and month), keep rows that carry a
-- numeric count, drop category banners, subtotal formulas, blank rows and notes.
with cells as (
    select c.*, r.rel_path
    from {{ source('raw', 'sheet_cells') }} c
    join {{ source('raw', '_file_registry') }} r on r.file_id = c._file_id and r.status = 'LOADED'
    where c.sheet_kind = 'count'
), hdr as (
    select rel_path, min(cast(sheet_row as integer)) as header_row
    from cells where lower(c5) in ('counted qty', 'qty counted', 'on hand', 'oh') group by 1
), kept as (
    select c.*, h.header_row
    from cells c join hdr h using (rel_path)
    where cast(c.sheet_row as integer) > h.header_row and c.c2 is not null and substr(c.cell_types, 5, 1) = 'n' and c.c1 not like 'Subtotal%'
)
select
    rel_path, cast(sheet_row as integer) as sheet_row,
    regexp_extract(rel_path, 'count_sheets/(WH-0[0-9])/', 1) as wh_code,
    regexp_extract(rel_path, '/([0-9]{4}-[0-9]{2})_count', 1) as file_month,
    trim(c1) as sku_raw, c2 as description, c3 as bin, c4 as uom,
    try_cast(c5 as double) as counted_qty, c6 as counted_by, c7 as date_raw, substr(cell_types, 7, 1) as date_type,
    case when substr(cell_types, 7, 1) = 'd' then cast(try_cast(c7 as timestamp) as date)
         else coalesce(cast(try_strptime(c7, '%m/%d/%Y') as date), cast(try_strptime(c7, '%d-%b-%y') as date)) end as count_date,
    c8 as note
from kept
