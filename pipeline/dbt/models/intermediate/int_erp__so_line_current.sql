-- Latest version of every sales-order line (nightly extracts carry every change).
select * from {{ ref('stg_erp__so_line_versions') }}
qualify row_number() over (partition by order_no, line_no order by extract_date desc, last_modified_local desc, _file_id desc, _row_num desc) = 1
