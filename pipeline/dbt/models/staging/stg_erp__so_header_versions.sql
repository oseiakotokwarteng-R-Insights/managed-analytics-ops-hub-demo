select
    order_no, cust_acct,
    try_cast(order_ts_local as timestamp)    as order_ts_local,
    try_cast(req_date as date)               as req_date,
    ship_via, status,
    try_cast(last_modified as timestamp)     as last_modified_local,
    try_cast(extract_date as date)           as extract_date,
    _file_id, _row_num
from {{ source('raw', 'erp_sales_order_header') }}
