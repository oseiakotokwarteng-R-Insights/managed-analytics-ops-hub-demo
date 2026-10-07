-- What the warehouse actually picked for each order, by ERP item. Independent evidence about what was ordered.
select e.ref_no as order_no, x.item_no, sum(e.quantity) as picked_qty
from {{ ref('stg_wms__event') }} e
join {{ ref('xwalk_sku') }} x on x.source_system = 'WMS_ITEM_ID' and x.source_key = cast(e.item_id as varchar)
where e.event_type = 'PICK'
group by 1, 2
