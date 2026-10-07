{{ config(materialized='table') }}
-- F2: carrier references arrive with case, hyphen and zero-padding variants, and the occasional keyed digit error.
-- A keyed error can land exactly on ANOTHER valid order number, so no match is trusted on the number alone. A document is accepted only if
-- its evidence agrees with the shipment: ship date (orders) or receipt date (POs) within a day, the shipped/received weight, and the cities.
--   1. normalise the reference and test the document it names;
--   2. if that fails the evidence (or does not exist), take the single document one edit away that does agree;
--   3. otherwise review. Nothing is guessed.
with n as (
    select *, regexp_replace(upper(trim(ref_raw)), '^(SO|PO)-?0?([0-9]{6})$', '\1-\2') as ref_norm,
           cast(pickup_ts_utc as date) as pickup_date, cast(delivered_ts_raw as date) as delivered_date
    from {{ ref('int_shipment_raw') }}
),
so_doc as (
    select o.order_no as doc_no, 'SO' as doc_type, w.city as origin_city, c.ship_to_city as dest_city
    from (select order_no, min(wh_code) as wh_code, min(cust_acct) as cust_acct from {{ ref('fct_order_line') }} group by 1) o
    join {{ ref('dim_warehouse') }} w on w.wh_code = o.wh_code
    left join {{ ref('stg_erp__customer') }} c on c.cust_acct = o.cust_acct
),
po_doc as (
    select h.po_no as doc_no, 'PO' as doc_type, v.city as origin_city, w.city as dest_city
    from {{ ref('int_erp__po_header_current') }} h
    join {{ ref('stg_erp__vendor') }} v on v.vendor_no = h.vendor_no
    join {{ ref('dim_warehouse') }} w on w.wh_code = h.ship_to_wh
),
docs as (select * from so_doc union all select * from po_doc),
exact_c as (
    select n.shipment_key, d.doc_no,
           (   (d.doc_type = 'SO' and exists (select 1 from {{ ref('int_doc_shipped_weight') }} s where s.doc_no = d.doc_no and s.d between n.pickup_date - 1 and n.pickup_date + 1))
            or (d.doc_type = 'PO' and exists (select 1 from {{ ref('int_doc_shipped_weight') }} s where s.doc_no = d.doc_no and s.d between n.delivered_date - 1 and n.delivered_date + 1)))
           and (n.origin_city is null or n.origin_city = d.origin_city) and (n.dest_city is null or n.dest_city = d.dest_city) as weak_ok,
           (   (d.doc_type = 'SO' and exists (select 1 from {{ ref('int_doc_shipped_weight') }} s where s.doc_no = d.doc_no and s.d between n.pickup_date - 1 and n.pickup_date + 1
                                                 and (n.weight_lb_reported is null or abs(s.w - n.weight_lb_reported) <= 0.15 * n.weight_lb_reported + 2)))
            or (d.doc_type = 'PO' and exists (select 1 from {{ ref('int_doc_shipped_weight') }} s where s.doc_no = d.doc_no and s.d between n.delivered_date - 1 and n.delivered_date + 1
                                                 and (n.weight_lb_reported is null or abs(s.w - n.weight_lb_reported) <= 0.15 * n.weight_lb_reported + 2))))
           and (n.origin_city is null or n.origin_city = d.origin_city) and (n.dest_city is null or n.dest_city = d.dest_city) as strong_ok
    from n join docs d on d.doc_no = n.ref_norm
),
fuzzy as (
    select t.shipment_key, d.doc_no
    from (select n.* from n where n.shipment_key not in (select shipment_key from exact_c where strong_ok)) t
    join docs d on damerau_levenshtein(t.ref_norm, d.doc_no) = 1 and left(d.doc_no, 2) = left(t.ref_norm, 2)
    where (   (d.doc_type = 'SO' and exists (select 1 from {{ ref('int_doc_shipped_weight') }} s where s.doc_no = d.doc_no and s.d between t.pickup_date - 1 and t.pickup_date + 1
                                                and (t.weight_lb_reported is null or abs(s.w - t.weight_lb_reported) <= 0.15 * t.weight_lb_reported + 2)))
           or (d.doc_type = 'PO' and exists (select 1 from {{ ref('int_doc_shipped_weight') }} s where s.doc_no = d.doc_no and s.d between t.delivered_date - 1 and t.delivered_date + 1
                                                and (t.weight_lb_reported is null or abs(s.w - t.weight_lb_reported) <= 0.15 * t.weight_lb_reported + 2))))
      and (t.origin_city is null or t.origin_city = d.origin_city) and (t.dest_city is null or t.dest_city = d.dest_city)
),
fuzzy_u as (select shipment_key, min(doc_no) as doc_no, count(*) as n from fuzzy group by 1),
j as (
    select n.shipment_key, n.carrier, n.ref_raw, n.ref_norm, e.doc_no as exact_doc, coalesce(e.strong_ok, false) as exact_strong, coalesce(e.weak_ok, false) as exact_weak,
           coalesce(f.n, 0) as n_fuzzy, f.doc_no as fuzzy_doc
    from n left join exact_c e using (shipment_key) left join fuzzy_u f using (shipment_key)
)
select shipment_key, carrier, ref_raw, ref_norm,
       case when exact_strong then exact_doc
            when not exact_weak and n_fuzzy = 1 then fuzzy_doc
            when exact_weak and n_fuzzy = 0 then exact_doc end as doc_no,
       case when exact_strong then 'normalized_with_evidence'
            when not exact_weak and n_fuzzy = 1 then 'single_edit_with_evidence'
            when exact_weak and n_fuzzy = 0 then 'normalized_date_and_city_only'
            when exact_weak and n_fuzzy >= 1 then 'conflict_named_document_vs_one_edit_candidate'
            when exact_doc is not null then 'named_document_contradicted_by_evidence'
            else 'unmatched' end as match_method,
       case when exact_strong or (not exact_weak and n_fuzzy = 1) or (exact_weak and n_fuzzy = 0) then 'AUTO' else 'REVIEW' end as status
from j
