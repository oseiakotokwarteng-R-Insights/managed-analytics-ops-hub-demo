{{ config(materialized='table') }}
-- The canonical stock ledger: every movement that changes (or that the systems claim changed) stock, by item and warehouse.
-- Recorded movements come from the WMS and the legacy system; inferred movements fill gaps proven by cross-system evidence.
with wms_item as (
    select e.*, x.item_no, x.valid_from as linked_from
    from {{ ref('stg_wms__event') }} e
    join {{ ref('xwalk_sku') }} x on x.source_system = 'WMS_ITEM_ID' and x.source_key = cast(e.item_id as varchar)
),
recorded_wms as (
    select
        w.event_id as movement_id, 'WMS' as source_system, w.wh_code, coalesce(rf.corrected_item_no, w.item_no) as item_no, w.item_no as recorded_item_no, w.local_date, w.event_ts_utc as ts_utc,
        case w.event_type when 'RECEIVE' then 'RECEIPT' when 'SHIP' then 'SHIPMENT' when 'TRANSFER_IN' then 'TRANSFER_IN'
                          when 'TRANSFER_OUT' then 'TRANSFER_OUT' when 'OPENING_BALANCE' then 'OPENING'
                          when 'ADJUST' then case when w.reason = 'CYCLE_COUNT' then 'COUNT_ADJUSTMENT' else 'WRITE_OFF' end end as movement_type,
        case w.direction when 'IN' then w.quantity else -w.quantity end as qty_delta,
        coalesce(w.reason = 'CYCLE_COUNT', false) as is_count_adjustment,
        w.ref_no, false as is_inferred, cast(null as varchar) as inference_rule, cast(null as double) as evidence_score,
        case when rf.corrected_item_no is not null then 'receipt_item_corrected_from_po'
             when w.local_date < w.linked_from then 'item_linked_late' end as quality_flag
    from wms_item w
    left join {{ ref('int_wms__receipt_fix') }} rf on rf.event_id = w.event_id and rf.status = 'AUTO'
    where w.event_type in ('RECEIVE', 'SHIP', 'TRANSFER_IN', 'TRANSFER_OUT', 'OPENING_BALANCE', 'ADJUST')
),
recorded_legacy as (
    select
        t.trans_id as movement_id, 'LEGACY' as source_system, 'WH-05' as wh_code, r.item_no, r.item_no as recorded_item_no, r.date_resolved as local_date, cast(null as timestamptz) as ts_utc,
        case t.trans_type when 'RCPT' then 'RECEIPT' when 'ISSU' then 'SHIPMENT' when 'XFER' then 'TRANSFER_IN' when 'OPEN' then 'OPENING'
                          else case when t.memo = 'COUNT' then 'COUNT_ADJUSTMENT' else 'WRITE_OFF' end end as movement_type,
        case when t.trans_type in ('RCPT', 'XFER', 'OPEN', 'ADJ+') then t.qty else -t.qty end as qty_delta,
        t.memo = 'COUNT' as is_count_adjustment,
        t.ref_no, false as is_inferred, cast(null as varchar) as inference_rule, cast(null as double) as evidence_score,
        case when r.date_unresolved then 'date_ambiguous_default_used' end as quality_flag
    from {{ ref('stg_legacy__trans') }} t
    join {{ ref('int_legacy__resolved') }} r using (trans_id)
    where r.item_no is not null and t.qty is not null
),
-- W6 / C2: picked and packed but the ship confirmation never arrived. ERP says the order shipped -> infer the shipment on the pack date.
picks as (
    select e.event_id, e.wh_code, e.item_no, e.ref_no, e.quantity,
           (select min(p.local_date) from wms_item p where p.ref_no = e.ref_no and p.item_no = e.item_no and p.event_type = 'PACK' and p.local_date >= e.local_date) as pack_date,
           e.local_date as pick_date
    from wms_item e where e.event_type = 'PICK'
),
unshipped as (
    select p.* from picks p
    where not exists (select 1 from wms_item s where s.ref_no = p.ref_no and s.item_no = p.item_no and s.event_type = 'SHIP')
),
erp_shipped as (
    select distinct order_no from {{ ref('int_erp__so_line_current') }} where qty_shipped > 0
),
inferred_ship as (
    select
        'INF-SHIP-' || u.event_id as movement_id, 'INFERRED' as source_system, u.wh_code, u.item_no, u.item_no as recorded_item_no,
        coalesce(u.pack_date, u.pick_date) as local_date, cast(null as timestamptz) as ts_utc,
        'SHIPMENT' as movement_type, -u.quantity as qty_delta, false as is_count_adjustment, u.ref_no,
        true as is_inferred, 'picked_and_packed_but_no_ship_event_erp_shows_shipped' as inference_rule,
        0.5 + (case when u.pack_date is not null then 0.2 else 0 end) as evidence_score,
        cast(null as varchar) as quality_flag
    from unshipped u join erp_shipped es on es.order_no = u.ref_no
),
-- C3: a transfer-in with no recorded transfer-out. The hub is the warehouse that sends every recorded transfer; infer the missing out-side.
tr_out as (select ref_no, wh_code, local_date, item_no from recorded_wms where movement_type = 'TRANSFER_OUT'),
tr_in as (
    select * from recorded_wms where movement_type = 'TRANSFER_IN'
    union all
    select * from recorded_legacy where movement_type = 'TRANSFER_IN'
),
hub as (select wh_code from tr_out group by 1 order by count(*) desc limit 1),
lag_by_dest as (
    select i.wh_code, quantile_disc(date_diff('day', o.local_date, i.local_date), 0.5) as typical_lag_days
    from tr_in i join tr_out o using (ref_no) group by 1
),
inferred_out as (
    select
        'INF-TOUT-' || i.movement_id as movement_id, 'INFERRED' as source_system, (select wh_code from hub) as wh_code, i.item_no, i.item_no as recorded_item_no,
        i.local_date - cast(coalesce(l.typical_lag_days, 1) as integer) as local_date, cast(null as timestamptz) as ts_utc,
        'TRANSFER_OUT' as movement_type, -i.qty_delta as qty_delta, false as is_count_adjustment, i.ref_no,
        true as is_inferred, 'transfer_in_recorded_without_transfer_out' as inference_rule, cast(0.8 as double) as evidence_score, cast(null as varchar) as quality_flag
    from tr_in i
    left join lag_by_dest l on l.wh_code = i.wh_code
    where not exists (select 1 from tr_out o where o.ref_no = i.ref_no)
      -- an out-side dated before the window is already reflected in the opening balance
      and i.local_date - cast(coalesce(l.typical_lag_days, 1) as integer) >= cast('{{ var("history_start") }}' as date)
)
select * from recorded_wms
union all select * from recorded_legacy
union all select * from inferred_ship
union all select * from inferred_out
