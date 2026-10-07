{{ config(materialized='table') }}
-- Resolve each legacy transaction to an ERP item and a calendar date.
--   date: ambiguous DD/MM vs MM/DD readings are settled against ERP evidence (order ship dates, PO receipt dates) when available.
--   item: the 8-char code can map to several revisions. Tiers: (1) only one candidate exists on that date, (2) the candidate that the
--         referenced PO / order / hub transfer actually contains, (3) otherwise left unresolved (review queue).
with t as (select * from {{ ref('stg_legacy__trans') }}),
ship_dates as (select distinct order_no as ref_no, last_ship_date as d from {{ ref('int_erp__so_line_current') }} where last_ship_date is not null),
recv_dates as (select distinct po_no as ref_no, received_date as d from {{ ref('int_erp__po_line_current') }} where received_date is not null),
dated as (
    select t.trans_id,
        case
            when not t.date_ambiguous then t.trans_date
            -- a weekly dump only contains that week's transactions: the reading that falls inside the dump week wins
            when t.d_mdy between t.dump_date - 6 and t.dump_date and not (t.d_dmy between t.dump_date - 6 and t.dump_date) then t.d_mdy
            when t.d_dmy between t.dump_date - 6 and t.dump_date and not (t.d_mdy between t.dump_date - 6 and t.dump_date) then t.d_dmy
            when exists (select 1 from ship_dates s where s.ref_no = t.ref_no and s.d = t.d_mdy) and not exists (select 1 from ship_dates s where s.ref_no = t.ref_no and s.d = t.d_dmy) then t.d_mdy
            when exists (select 1 from ship_dates s where s.ref_no = t.ref_no and s.d = t.d_dmy) and not exists (select 1 from ship_dates s where s.ref_no = t.ref_no and s.d = t.d_mdy) then t.d_dmy
            when exists (select 1 from recv_dates s where s.ref_no = t.ref_no and s.d = t.d_mdy) and not exists (select 1 from recv_dates s where s.ref_no = t.ref_no and s.d = t.d_dmy) then t.d_mdy
            when exists (select 1 from recv_dates s where s.ref_no = t.ref_no and s.d = t.d_dmy) and not exists (select 1 from recv_dates s where s.ref_no = t.ref_no and s.d = t.d_mdy) then t.d_dmy
            else t.d_mdy
        end as date_resolved,
        t.date_ambiguous,
        t.date_ambiguous and not (
            (t.d_mdy between t.dump_date - 6 and t.dump_date) <> (t.d_dmy between t.dump_date - 6 and t.dump_date)
            or exists (select 1 from ship_dates s where s.ref_no = t.ref_no and s.d in (t.d_mdy, t.d_dmy))
            or exists (select 1 from recv_dates s where s.ref_no = t.ref_no and s.d in (t.d_mdy, t.d_dmy))) as date_unresolved
    from t
),
cand as (
    select t.trans_id, x.item_no
    from t join {{ ref('xwalk_sku') }} x on x.source_system = 'LEGACY_CODE' and x.source_key = t.legacy_code
),
cand_at as (
    select c.trans_id, c.item_no
    from cand c join dated d using (trans_id) join {{ ref('dim_sku') }} s on s.item_no = c.item_no
    where s.created_date <= d.date_resolved
),
evidence as (
    select t.trans_id, l.item_no from t join {{ ref('int_erp__po_line_current') }} l on l.po_no = t.ref_no where t.trans_type = 'RCPT'
    union
    -- An ERP order line can carry the predecessor's number when the successor shipped (defect E1), so a line naming a superseded item is
    -- not trustworthy evidence for a shipment. Only lines naming a current (non-superseded) item are accepted.
    select t.trans_id, l.item_no from t join {{ ref('int_erp__so_line_current') }} l on l.order_no = t.ref_no
    join {{ ref('dim_sku') }} s on s.item_no = l.item_no
    where t.trans_type = 'ISSU' and s.superseded_by is null
    union
    select t.trans_id, x.item_no
    from t
    join {{ ref('stg_wms__event') }} e on e.ref_no = t.ref_no and e.event_type = 'TRANSFER_OUT'
    join {{ ref('xwalk_sku') }} x on x.source_system = 'WMS_ITEM_ID' and x.source_key = cast(e.item_id as varchar)
    where t.trans_type = 'XFER'
),
by_date as (select trans_id, count(*) as n, min(item_no) as item_no from cand_at group by 1),
by_ev as (
    select ca.trans_id, count(*) as n, min(ca.item_no) as item_no
    from cand_at ca join evidence e on e.trans_id = ca.trans_id and e.item_no = ca.item_no group by 1
)
select
    t.trans_id, d.date_resolved, d.date_ambiguous, d.date_unresolved,
    coalesce(bd.n, 0) as n_candidates_at_date,
    case when bd.n = 1 then bd.item_no when be.n = 1 then be.item_no end as item_no,
    case when bd.n = 1 then 'unique_at_date' when be.n = 1 then 'ref_evidence' when coalesce(bd.n, 0) = 0 then 'no_candidate' else 'ambiguous' end as item_resolution,
    (select list_sort(list(distinct item_no)) from cand_at ca where ca.trans_id = t.trans_id) as candidate_items
from t
join dated d using (trans_id)
left join by_date bd using (trans_id)
left join by_ev be using (trans_id)
