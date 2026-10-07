{{ config(materialized='table') }}
-- Purchase-order lines still open at the end of history: what is coming, when it was promised, and how overdue it is.
select p.po_no, p.line_no, p.item_no, s.description, p.vendor_no, v.name as vendor_name, p.wh_code, p.po_date, p.promised_date, p.qty_ordered, p.unit_cost, p.qty_ordered * p.unit_cost as open_value,
       greatest(0, date_diff('day', p.promised_date, cast('{{ var("history_end") }}' as date))) as days_overdue
from {{ ref('fct_po_line') }} p
join {{ ref('dim_sku') }} s using (item_no)
left join {{ ref('dim_vendor') }} v on v.vendor_no = p.vendor_no
where p.received_date is null
