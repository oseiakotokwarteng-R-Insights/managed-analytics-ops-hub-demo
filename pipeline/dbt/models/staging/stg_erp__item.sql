-- ERP item master: the system of record for item identity. Latest snapshot wins.
select
    item_no, description, category, uom,
    try_cast(case_qty as integer)        as case_qty,
    nullif(case_uom, '')                 as case_uom,
    try_cast(list_price as double)       as list_price,
    try_cast(std_cost as double)         as std_cost,
    try_cast(weight_lb as double)        as weight_lb,
    vendor_no, status,
    nullif(superseded_by, '')            as superseded_by,
    try_cast(created_date as date)       as created_date,
    try_cast(wms_item_id as bigint)      as wms_item_id,
    try_cast(wms_link_date as date)      as wms_link_date
from {{ source('raw', 'erp_item_master') }}
qualify row_number() over (partition by item_no order by _file_id desc, _row_num) = 1
