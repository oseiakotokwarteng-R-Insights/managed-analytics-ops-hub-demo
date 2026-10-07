-- Legacy rows kept out of the ledger, with the reason. They stay here (and in core.review_queue) until a person or a later rule resolves them.
select t.trans_id, t.legacy_code, t.trans_type, t.trans_date_raw, t.qty_raw, t.ref_no, r.item_resolution, r.candidate_items,
       case when t.qty is null then 'L5_QUANTITY_UNPARSEABLE' else 'L1_ITEM_AMBIGUOUS' end as reason_code
from {{ ref('stg_legacy__trans') }} t join {{ ref('int_legacy__resolved') }} r using (trans_id)
where t.qty is null or r.item_no is null
