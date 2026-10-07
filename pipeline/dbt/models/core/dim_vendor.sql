select vendor_no, name, city, quoted_lead_time_days, is_import from {{ ref('stg_erp__vendor') }}
