select
    po_no, cast(line_no as integer)          as line_no, item_no,
    try_cast(qty_ordered as double)          as qty_ordered,
    try_cast(unit_cost as double)            as unit_cost,
    try_cast(qty_received as double)         as qty_received,
    try_cast(received_date as date)          as received_date,
    status,
    try_cast(extract_date as date)           as extract_date,
    _file_id, _row_num
from {{ source('raw', 'erp_po_line') }}
