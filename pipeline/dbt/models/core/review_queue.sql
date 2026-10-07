-- Everything the pipeline would not decide on its own. Nothing here has been silently dropped or guessed.
-- Each reason code is governed in ref.dq_reason_codes (severity, owner, suggested action).
select q.*, r.defect_class, r.severity, r.disposition, r.owner_role, r.suggested_action
from (
select 'LEGACY' as source_system, trans_id as source_key, reason_code, 'item candidates: ' || coalesce(array_to_string(candidate_items, ', '), 'none') as detail
from {{ ref('q_legacy_trans') }}
union all
select 'SHEETS', count_key, reason_code, 'sku as written: ' || sku_raw from {{ ref('q_count_row') }}
union all
select 'WMS', event_id, 'W5_RECEIPT_ITEM_UNRESOLVED', 'received ' || recorded_item_no || ' on ' || po_no from {{ ref('int_wms__receipt_fix') }} where status = 'UNRESOLVED'
union all
select 'FREIGHT', shipment_key, 'F2_REFERENCE_UNMATCHED', 'reference as written: ' || ref_raw from {{ ref('int_shipment_ref_match') }} where status = 'REVIEW'
union all
select 'LEGACY', legacy_vendor_id, 'L6_VENDOR_WEAK_MATCH', 'closest ERP vendor ' || vendor_no || ' (similarity ' || cast(round(confidence, 2) as varchar) || ')' from {{ ref('xwalk_vendor') }} where status = 'REVIEW'
union all
select 'ERP', order_no || '|' || cast(line_no as varchar), 'E2_NEAR_DUPLICATE_ORDER_LINE', 'same customer, item and quantity 11-25 minutes after another order' from {{ ref('fct_order_line') }} where flag_near_duplicate and not is_duplicate
union all
select 'ERP', order_no || '|' || cast(line_no as varchar), exclude_reason, 'excluded from fct_order_line analytics' from {{ ref('fct_order_line') }} where exclude_reason is not null and not is_duplicate
union all
select 'WMS', event_id, 'C3_TRANSFER_OUT_WITHOUT_IN', 'item ' || item_no || ' qty ' || cast(quantity as varchar) || ' from ' || from_wh from {{ ref('recon_transfer_exceptions') }}
union all
select 'ERP', po_no || '|' || cast(line_no as varchar), 'C1_RECEIPT_QUANTITY_VARIANCE', 'erp ' || cast(qty_received_erp as varchar) || ' vs warehouse ' || cast(qty_received_warehouse as varchar) from {{ ref('recon_receipt_variance') }}
union all
select 'SHEETS', vendor_name || '|' || item_no || '|' || cast(effective_date as varchar), 'X6_PRICE_CONFLICT',
       'prices ' || string_agg(cast(override_cost as varchar) || ' (entered ' || cast(cast(entered_on as date) as varchar) || ')', ' vs ' order by entered_on, row_key) || '; the later entry is used until confirmed'
from {{ ref('recon_price_conflicts') }} group by vendor_name, item_no, effective_date
) q
left join {{ ref('dq_reason_codes') }} r using (reason_code)
