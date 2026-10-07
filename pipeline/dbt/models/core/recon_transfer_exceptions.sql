-- C3: transfer-outs the receiving side never recorded. The destination is not in the out-event, so these stay as in-transit exceptions.
with outs as (
    select e.event_id, e.ref_no, e.wh_code as from_wh, e.local_date as out_date, x.item_no, e.quantity
    from {{ ref('stg_wms__event') }} e
    join {{ ref('xwalk_sku') }} x on x.source_system = 'WMS_ITEM_ID' and x.source_key = cast(e.item_id as varchar)
    where e.event_type = 'TRANSFER_OUT'
), ins as (
    select ref_no from {{ ref('fct_stock_movement') }} where movement_type = 'TRANSFER_IN' and not is_inferred
)
select o.*, 'transfer_out_without_transfer_in' as exception_type
from outs o where o.ref_no not in (select ref_no from ins)
