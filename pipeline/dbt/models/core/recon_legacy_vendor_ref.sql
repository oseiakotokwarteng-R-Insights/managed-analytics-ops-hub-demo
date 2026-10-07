-- L4: legacy receipts whose vendor id is not in the legacy vendor master. The movement is valid; the vendor is repaired from the ERP PO.
select t.trans_id, t.ref_no as po_no, t.party_id as legacy_vendor_id, h.vendor_no as vendor_from_po,
       case when h.vendor_no is not null then 'AUTO_REPAIRED_FROM_PO' else 'REVIEW' end as status
from {{ ref('stg_legacy__trans') }} t
left join {{ ref('stg_legacy__vendor') }} v on v.vendor_id = t.party_id
left join {{ ref('int_erp__po_header_current') }} h on h.po_no = t.ref_no
where t.trans_type = 'RCPT' and v.vendor_id is null
