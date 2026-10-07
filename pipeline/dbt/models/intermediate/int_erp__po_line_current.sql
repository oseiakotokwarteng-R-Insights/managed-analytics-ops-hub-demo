select * from {{ ref('stg_erp__po_line_versions') }}
qualify row_number() over (partition by po_no, line_no order by extract_date desc, _file_id desc, _row_num desc) = 1
