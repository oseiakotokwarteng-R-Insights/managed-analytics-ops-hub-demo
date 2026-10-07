-- Item/warehouse/day combinations where a recorded movement could not be used (unparseable quantity, unresolved item).
-- Stock estimates are flagged from that day until the next count.
select r.item_no, 'WH-05' as wh_code, r.date_resolved as local_date, 'legacy_quantity_unparseable' as reason
from {{ ref('stg_legacy__trans') }} t join {{ ref('int_legacy__resolved') }} r using (trans_id)
where t.qty is null and r.item_no is not null
union all
select unnest(r.candidate_items), 'WH-05', r.date_resolved, 'legacy_item_unresolved'
from {{ ref('stg_legacy__trans') }} t join {{ ref('int_legacy__resolved') }} r using (trans_id)
where r.item_no is null and r.candidate_items is not null
