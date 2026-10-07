-- Nothing may disappear between layers without a recorded reason. Each row compares what went in with what came out plus what was set aside.
with c as (
    select 'wms: raw rows = unique staged events + duplicate copies' as check_name,
           (select count(*) from {{ source('raw', 'wms_events') }}) as left_count,
           (select count(*) + sum(n_copies - 1) from {{ ref('stg_wms__event') }}) as right_count
    union all select 'wms: staged stock events = ledger rows from the WMS (every item resolved)',
           (select count(*) from {{ ref('stg_wms__event') }} where event_type in ('RECEIVE', 'SHIP', 'TRANSFER_IN', 'TRANSFER_OUT', 'OPENING_BALANCE', 'ADJUST')),
           (select count(*) from {{ ref('fct_stock_movement') }} where source_system = 'WMS')
    union all select 'legacy: staged rows = ledger rows + quarantined rows',
           (select count(*) from {{ ref('stg_legacy__trans') }}),
           (select count(*) from {{ ref('fct_stock_movement') }} where source_system = 'LEGACY') + (select count(*) from {{ ref('q_legacy_trans') }})
    union all select 'erp sales lines: distinct (order, line) in all versions = cleaned order-line rows',
           (select count(*) from (select distinct order_no, line_no from {{ ref('stg_erp__so_line_versions') }})), (select count(*) from {{ ref('fct_order_line') }})
    union all select 'erp po lines: distinct (po, line) in all versions = po-line rows',
           (select count(*) from (select distinct po_no, line_no from {{ ref('stg_erp__po_line_versions') }})), (select count(*) from {{ ref('fct_po_line') }})
    union all select 'count sheets: staged count rows = count facts',
           (select count(*) from {{ ref('stg_sheets__count_row') }}), (select count(*) from {{ ref('fct_count') }})
    union all select 'carrier a: distinct shipments = shipment facts',
           (select count(distinct bol_no) from {{ ref('stg_carrier_a__shipment_versions') }}), (select count(*) from {{ ref('fct_shipment') }} where carrier = 'CARRIER_A')
    union all select 'carrier b: distinct shipments = shipment facts',
           (select count(distinct tracking_no) from {{ source('raw', 'carrier_b_shipments') }}), (select count(*) from {{ ref('fct_shipment') }} where carrier = 'CARRIER_B')
    union all select 'quarantine: every quarantined legacy or count row is in the review queue',
           (select count(*) from {{ ref('q_legacy_trans') }}) + (select count(*) from {{ ref('q_count_row') }}),
           (select count(*) from {{ ref('review_queue') }} where reason_code in ('L5_QUANTITY_UNPARSEABLE', 'L1_ITEM_AMBIGUOUS', 'sku_unresolved', 'date_outside_sheet_month'))
)
select check_name, left_count, right_count, left_count - right_count as diff, left_count = right_count as ok from c
