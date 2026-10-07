-- Every version of every sales-order line, as extracted nightly. Quantities may be in cases (uom = 'CS').
select
    order_no, cast(line_no as integer)       as line_no, item_no,
    try_cast(qty_ordered as double)          as qty_ordered,
    try_cast(qty_shipped as double)          as qty_shipped,
    uom,
    try_cast(unit_price as double)           as unit_price,
    nullif(ship_wh, '')                      as ship_wh,
    status,
    try_cast(last_ship_date as date)         as last_ship_date,
    try_cast(last_modified as timestamp)     as last_modified_local,
    try_cast(extract_date as date)           as extract_date,
    _file_id, _row_num
from {{ source('raw', 'erp_sales_order_line') }}
