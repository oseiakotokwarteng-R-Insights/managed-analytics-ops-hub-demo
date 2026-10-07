{{ config(materialized='table') }}
-- Clean sales-order lines. Each ERP defect has an explicit rule; nothing is changed silently (see the flag columns).
--   E1 successor item keyed as its predecessor -> remapped when the warehouse picked the successor for that order
--   E2 re-keyed duplicates                     -> exact duplicates dropped (is_duplicate); 11-25 minute near-matches only flagged
--   E3 zero/negative quantity                  -> excluded
--   E4 ship-from warehouse null/invalid        -> filled from the customer's default warehouse, else from a sibling line
--   E5 quantity in cases                       -> converted to units with the item master's case size; E5b (no case size) excluded
--   E6 quantity changed after shipment         -> both the original and the current quantity are kept
with cur as (select * from {{ ref('int_erp__so_line_current') }}),
first_v as (select * from {{ ref('int_erp__so_line_first') }}),
hdr as (
    select h.*, c.default_wh from {{ ref('int_erp__so_header_current') }} h left join {{ ref('stg_erp__customer') }} c on c.cust_acct = h.cust_acct
),
valid_wh as (select wh_code from {{ ref('dim_warehouse') }}),
j as (
    select cur.*, f.qty_ordered_first, h.cust_acct, h.order_ts_local, h.default_wh, s.case_qty, s.superseded_by,
           case when cur.ship_wh in (select wh_code from valid_wh) then cur.ship_wh end as ship_wh_valid
    from cur join first_v f using (order_no, line_no)
    left join hdr h using (order_no)
    left join {{ ref('dim_sku') }} s on s.item_no = cur.item_no
),
sib as (select order_no, min(ship_wh_valid) as sibling_wh from j group by 1),
dup_same as (
    select a.order_no, a.line_no from j a
    where a.status = 'OPEN' and a.qty_shipped = 0
      and exists (select 1 from j b where b.order_no = a.order_no and b.item_no = a.item_no and b.qty_ordered = a.qty_ordered and b.line_no < a.line_no)
),
dup_new as (
    select a.order_no, a.line_no, min(date_diff('minute', b.order_ts_local, a.order_ts_local)) as gap_min
    from j a join j b on b.cust_acct = a.cust_acct and b.item_no = a.item_no and b.qty_ordered = a.qty_ordered and b.order_no <> a.order_no
         and b.order_ts_local < a.order_ts_local and a.order_ts_local <= b.order_ts_local + interval 25 minute
    where a.status = 'OPEN' and a.qty_shipped = 0
    group by 1, 2
),
e1 as (
    select j.order_no, j.line_no, j.superseded_by as corrected_item
    from j
    where j.superseded_by is not null
      and exists (select 1 from {{ ref('int_wms__order_items') }} o where o.order_no = j.order_no and o.item_no = j.superseded_by)
      and not exists (select 1 from {{ ref('int_wms__order_items') }} o where o.order_no = j.order_no and o.item_no = j.item_no)
)
select
    j.order_no, j.line_no, j.cust_acct,
    coalesce(e1.corrected_item, j.item_no) as item_no, j.item_no as item_no_as_entered,
    coalesce(j.ship_wh_valid, j.default_wh, sib.sibling_wh) as wh_code,
    (j.order_ts_local at time zone w.timezone) as order_ts_utc,
    case when j.uom = 'CS' then j.qty_ordered * coalesce(ck.case_qty, j.case_qty) else j.qty_ordered end as qty_ordered_units,
    case when j.uom = 'CS' then j.qty_ordered_first * coalesce(ck.case_qty, j.case_qty) else j.qty_ordered_first end as qty_ordered_units_original,
    case when j.uom = 'CS' then j.qty_shipped * coalesce(ck.case_qty, j.case_qty) else j.qty_shipped end as qty_shipped_units,
    case when j.uom = 'CS' then j.unit_price / coalesce(ck.case_qty, j.case_qty) else j.unit_price end as unit_price,
    j.status, j.last_ship_date,
    (e1.corrected_item is not null) as flag_item_remapped,
    (j.ship_wh_valid is null) as flag_wh_filled,
    (j.uom = 'CS') as flag_uom_converted,
    (j.qty_ordered_first <> j.qty_ordered) as flag_modified_after_entry,
    (ds.order_no is not null or (dn.gap_min is not null and dn.gap_min <= 10)) as is_duplicate,
    (dn.gap_min is not null and dn.gap_min > 10) as flag_near_duplicate,
    case when j.qty_ordered <= 0 then 'E3_QUANTITY_NOT_POSITIVE'
         when j.uom = 'CS' and coalesce(ck.case_qty, j.case_qty) is null then 'E5B_NO_CASE_SIZE'
         when coalesce(j.ship_wh_valid, j.default_wh, sib.sibling_wh) is null then 'E4_WAREHOUSE_UNKNOWN' end as exclude_reason
from j
left join e1 using (order_no, line_no)
left join sib using (order_no)
left join dup_same ds using (order_no, line_no)
left join dup_new dn using (order_no, line_no)
left join {{ ref('dim_sku') }} ck on ck.item_no = e1.corrected_item
left join {{ ref('dim_warehouse') }} w on w.wh_code = coalesce(j.ship_wh_valid, j.default_wh, sib.sibling_wh)
