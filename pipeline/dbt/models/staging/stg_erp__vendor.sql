select vendor_no, name, city, try_cast(quoted_lead_time_days as integer) as quoted_lead_time_days, is_import = 'Y' as is_import
from {{ source('raw', 'erp_vendor_master') }}
qualify row_number() over (partition by vendor_no order by _file_id desc) = 1
