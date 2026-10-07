-- What each order shipped (by ship date) and each PO received (by receipt date), in pounds. Used as evidence when matching carrier shipments.
select l.order_no as doc_no, l.last_ship_date as d, round(sum(l.qty_shipped_units * s.weight_lb), 3) as w
from {{ ref('fct_order_line') }} l join {{ ref('dim_sku') }} s on s.item_no = l.item_no
where not l.is_duplicate and l.qty_shipped_units > 0 and l.last_ship_date is not null
group by 1, 2
union all
select m.ref_no as doc_no, m.local_date as d, round(sum(m.qty_delta * s.weight_lb), 3) as w
from {{ ref('fct_stock_movement') }} m join {{ ref('dim_sku') }} s on s.item_no = m.item_no
where m.movement_type = 'RECEIPT' and m.ref_no like 'PO-%' and not m.is_inferred
group by 1, 2
