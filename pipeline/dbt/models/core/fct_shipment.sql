{{ config(materialized='table') }}
-- One row per carrier shipment, matched to its order or PO. F4: an impossible delivery time is dropped (flagged), never trusted.
-- F5: a missing weight is imputed from the matched document's item weights (flagged and sourced).
with r as (select * from {{ ref('int_shipment_raw') }}),
m as (select * from {{ ref('int_shipment_ref_match') }}),
so_w as (
    select l.order_no as doc_no, l.last_ship_date, round(sum(l.qty_shipped_units * s.weight_lb), 3) as w
    from {{ ref('fct_order_line') }} l join {{ ref('dim_sku') }} s on s.item_no = l.item_no
    where not l.is_duplicate and l.qty_shipped_units > 0 group by 1, 2
),
po_w as (
    select l.po_no as doc_no, round(sum(l.qty_received_erp * s.weight_lb), 3) as w
    from {{ ref('fct_po_line') }} l join {{ ref('dim_sku') }} s on s.item_no = l.item_no group by 1
)
select
    r.carrier, r.shipment_key, r.ref_raw, m.doc_no, m.match_method, m.status as match_status,
    case when left(m.doc_no, 2) = 'SO' then 'outbound' when left(m.doc_no, 2) = 'PO' then 'inbound' end as direction,
    r.origin_city, r.dest_city, r.pickup_ts_utc,
    case when r.delivered_ts_raw >= r.pickup_ts_utc and r.delivered_ts_raw <= r.pickup_ts_utc + interval 20 day then r.delivered_ts_raw end as delivered_ts_utc,
    (r.delivered_ts_raw is not null and not (r.delivered_ts_raw >= r.pickup_ts_utc and r.delivered_ts_raw <= r.pickup_ts_utc + interval 20 day)) as flag_delivery_time_invalid,
    r.weight_lb_reported,
    coalesce(r.weight_lb_reported, imp.w) as weight_lb,
    case when r.weight_lb_reported is not null then 'reported' when imp.w is not null then 'imputed_from_document' else 'missing_not_recoverable' end as weight_source,
    r.pieces_reported as pieces, r.pieces_reported is null as flag_pieces_missing
from r
left join m using (shipment_key)
left join lateral (
    select case when left(m.doc_no, 2) = 'SO'
                then (select round(sum(sw.w), 3) from so_w sw where sw.doc_no = m.doc_no and sw.last_ship_date between cast(r.pickup_ts_utc as date) - 1 and cast(r.pickup_ts_utc as date) + 1)
                else (select pw.w from po_w pw where pw.doc_no = m.doc_no) end as w
) imp on true
