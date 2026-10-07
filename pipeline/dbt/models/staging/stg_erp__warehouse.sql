select wh_code, name, city, timezone
from {{ source('raw', 'erp_warehouse_master') }}
qualify row_number() over (partition by wh_code order by _file_id desc) = 1
