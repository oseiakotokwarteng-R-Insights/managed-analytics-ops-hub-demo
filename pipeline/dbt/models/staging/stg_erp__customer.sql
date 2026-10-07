select
    cust_acct, name, cust_type, ship_to_city,
    nullif(default_wh, '')               as default_wh,
    terms,
    try_cast(discount_pct as double)     as discount_pct,
    try_cast(created_date as date)       as created_date,
    try_cast(inactive_date as date)      as inactive_date
from {{ source('raw', 'erp_customer_master') }}
qualify row_number() over (partition by cust_acct order by _file_id desc) = 1
