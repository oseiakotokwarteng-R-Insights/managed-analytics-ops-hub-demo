-- C1: the ERP receipt quantity disagrees with what the warehouse system recorded receiving. The warehouse is the physical record.
with wh as (
    select ref_no as po_no, item_no, sum(qty_delta) as qty_received_warehouse
    from {{ ref('fct_stock_movement') }} where movement_type = 'RECEIPT' and not is_inferred group by 1, 2
)
select l.po_no, l.line_no, l.item_no, l.wh_code, l.received_date, l.qty_ordered, l.qty_received_erp, w.qty_received_warehouse,
       l.qty_received_erp - w.qty_received_warehouse as variance
from {{ ref('fct_po_line') }} l join wh w on w.po_no = l.po_no and w.item_no = l.item_no
where l.received_date is not null and l.qty_received_erp <> w.qty_received_warehouse
