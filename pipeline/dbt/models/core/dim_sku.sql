-- One row per ERP item. The ERP is the system of record for item identity; every other system maps to item_no through core.xwalk_sku.
select
    i.item_no, i.description, i.category, i.uom, i.case_qty, i.case_uom, i.list_price, i.std_cost, i.weight_lb, i.vendor_no,
    i.status, i.superseded_by, p.item_no as predecessor_item_no, i.created_date, i.wms_item_id, i.wms_link_date,
    -- the acquired system's documented code scheme: 2-letter category + item number + check letter (A + number mod 26)
    c.code || regexp_extract(i.item_no, 'NF-([0-9]+)-', 1)
           || chr(65 + cast(regexp_extract(i.item_no, 'NF-([0-9]+)-', 1) as integer) % 26) as legacy_code
from {{ ref('stg_erp__item') }} i
left join {{ ref('legacy_category_codes') }} c on c.category = i.category
left join {{ ref('stg_erp__item') }} p on p.superseded_by = i.item_no
