select * from {{ ref('stg_erp__so_header_versions') }}
qualify row_number() over (partition by order_no order by extract_date desc, last_modified_local desc, _file_id desc, _row_num desc) = 1
