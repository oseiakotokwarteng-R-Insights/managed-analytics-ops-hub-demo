select l.po_no, l.line_no, l.item_no, h.vendor_no, h.ship_to_wh as wh_code, h.po_date, h.promised_date, h.received_date as header_received_date,
       l.qty_ordered, l.unit_cost, l.qty_received as qty_received_erp, l.received_date, l.status
from {{ ref('int_erp__po_line_current') }} l
left join {{ ref('int_erp__po_header_current') }} h using (po_no)
