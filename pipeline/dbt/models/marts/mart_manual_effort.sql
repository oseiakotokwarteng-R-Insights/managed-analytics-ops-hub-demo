{{ config(materialized='table') }}
-- MODELED estimate, not a measurement: how much manual reconciliation the pipeline replaces. Each handling count comes from the cleaned tables; minutes per item
-- are assumptions in seed ref.manual_effort_assumptions (shown in the dashboard). Rows the pipeline could not settle (review queue) are the work that remains.
with n as (
    select 'legacy_code_resolved' as handling_key, count(*) as items from {{ ref('fct_stock_movement') }} where source_system = 'LEGACY'
    union all select 'legacy_date_settled', count(*) from {{ ref('stg_legacy__trans') }} where date_ambiguous
    union all select 'legacy_vendor_repaired', count(*) from {{ ref('recon_legacy_vendor_ref') }}
    union all select 'receipt_item_corrected', count(*) from {{ ref('fct_stock_movement') }} where quality_flag = 'receipt_item_corrected_from_po'
    union all select 'ship_confirmation_inferred', count(*) from {{ ref('fct_stock_movement') }} where inference_rule = 'picked_and_packed_but_no_ship_event_erp_shows_shipped'
    union all select 'order_item_remapped', count(*) from {{ ref('fct_order_line') }} where flag_item_remapped
    union all select 'order_duplicate_dropped', count(*) from {{ ref('fct_order_line') }} where is_duplicate
    union all select 'order_case_converted', count(*) from {{ ref('fct_order_line') }} where flag_uom_converted
    union all select 'order_warehouse_filled', count(*) from {{ ref('fct_order_line') }} where flag_wh_filled
    union all select 'carrier_shipment_matched', count(*) from {{ ref('fct_shipment') }} where match_status = 'AUTO'
    union all select 'carrier_duplicate_flagged', count(*) from {{ ref('fct_freight_charge') }} where is_suspect_duplicate
    union all select 'count_sku_repaired', count(*) from {{ ref('fct_count') }} where sku_resolution = 'single_edit_repair'
    union all select 'count_compared_with_book', count(*) from {{ ref('fct_count') }} where is_anchor
    union all select 'review_queue_row', count(*) from {{ ref('review_queue') }}
)
select a.handling_key, a.label, a.minutes_per_item, a.basis, n.items, n.items * a.minutes_per_item / 60.0 as hours,
       a.handling_key = 'review_queue_row' as is_remaining_manual
from {{ ref('manual_effort_assumptions') }} a join n using (handling_key)
