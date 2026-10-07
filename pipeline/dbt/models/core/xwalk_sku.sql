-- Identifier crosswalk to the ERP item number. valid_from is when the mapping became usable; a legacy code can map to several items.
select 'WMS_ITEM_ID' as source_system, cast(wms_item_id as varchar) as source_key, wms_link_date as valid_from, item_no, 'erp_link_table' as match_method
from {{ ref('dim_sku') }} where wms_item_id is not null
union all
select 'LEGACY_CODE', legacy_code, created_date, item_no, 'documented_code_scheme' from {{ ref('dim_sku') }}
union all
select 'ERP_ITEM', item_no, created_date, item_no, 'identity' from {{ ref('dim_sku') }}
