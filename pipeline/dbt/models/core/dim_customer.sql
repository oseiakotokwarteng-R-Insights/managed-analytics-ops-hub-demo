select cust_acct, name, cust_type, ship_to_city, default_wh, default_wh is null as default_wh_missing, terms, discount_pct, created_date, inactive_date
from {{ ref('stg_erp__customer') }}
