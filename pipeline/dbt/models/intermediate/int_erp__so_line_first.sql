-- First version of every line: the quantity as originally entered (before any post-shipment change).
select order_no, line_no, item_no as item_no_first, qty_ordered as qty_ordered_first, uom as uom_first
from {{ ref('stg_erp__so_line_versions') }}
qualify row_number() over (partition by order_no, line_no order by extract_date, last_modified_local, _file_id, _row_num) = 1
