select
    r.rel_path, cast(c.sheet_row as integer) as sheet_row, c.c1 as vendor_name, trim(c.c2) as item_no,
    try_cast(c.c3 as double) as override_cost, cast(try_cast(c.c4 as timestamp) as date) as effective_date,
    try_cast(c.c5 as timestamp) as entered_on, c.c6 as entered_by
from {{ source('raw', 'sheet_cells') }} c
join {{ source('raw', '_file_registry') }} r on r.file_id = c._file_id and r.status = 'LOADED'
where c.sheet_kind = 'price' and c.c2 like 'NF-%' and substr(c.cell_types, 3, 1) = 'n'
