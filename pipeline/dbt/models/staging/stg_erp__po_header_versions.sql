select
    po_no, vendor_no, ship_to_wh,
    try_cast(po_date as date)                as po_date,
    try_cast(promised_date as date)          as promised_date,
    status,
    try_cast(received_date as date)          as received_date,
    try_cast(extract_date as date)           as extract_date,
    _file_id, _row_num
from {{ source('raw', 'erp_po_header') }}
