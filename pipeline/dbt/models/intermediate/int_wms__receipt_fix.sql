{{ config(materialized='table') }}
-- W5: a receipt keyed under the wrong item. The WMS receipt carries the PO number; the ERP PO lists the items actually ordered.
-- A receipt whose item is not on its PO, while exactly one PO line has no receipt that fits the quantity, was keyed to the wrong item.
with recv as (
    select e.event_id, e.ref_no as po_no, e.item_no, e.quantity, e.local_date, e.wh_code
    from (
        select ev.*, x.item_no from {{ ref('stg_wms__event') }} ev
        join {{ ref('xwalk_sku') }} x on x.source_system = 'WMS_ITEM_ID' and x.source_key = cast(ev.item_id as varchar)
        where ev.event_type = 'RECEIVE'
    ) e
),
po_items as (select po_no, item_no, qty_ordered from {{ ref('int_erp__po_line_current') }}),
bad as (
    select r.* from recv r
    where exists (select 1 from po_items p where p.po_no = r.po_no)                      -- the PO is known to the ERP
      and not exists (select 1 from po_items p where p.po_no = r.po_no and p.item_no = r.item_no)
),
missing as (
    select p.po_no, p.item_no, p.qty_ordered from po_items p
    where not exists (select 1 from recv r where r.po_no = p.po_no and r.item_no = p.item_no)
),
cand as (
    select b.event_id, m.item_no as corrected_item_no, m.qty_ordered - b.quantity as slack,
           count(*) over (partition by b.event_id) as n_cand
    from bad b join missing m on m.po_no = b.po_no and m.qty_ordered >= b.quantity
),
best as (
    select *, rank() over (partition by event_id order by slack) as rk from cand
)
select b.event_id, b.po_no, b.item_no as recorded_item_no, c.corrected_item_no, b.quantity, b.local_date, b.wh_code,
       case when c.corrected_item_no is null then 'UNRESOLVED' else 'AUTO' end as status,
       'receipt_item_not_on_po' as rule
from bad b
left join (select event_id, corrected_item_no from best where rk = 1 and (select count(*) from best b2 where b2.event_id = best.event_id and b2.rk = 1) = 1) c using (event_id)
