-- A shipment appears in several daily files as it progresses (and in re-sent files). Keep the most complete version.
select * from {{ ref('stg_carrier_a__shipment_versions') }}
qualify row_number() over (partition by bol_no order by n_events desc, has_charges desc, _file_id desc, _row_num desc) = 1
