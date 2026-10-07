{{ config(materialized='table') }}
-- Legacy inventory transactions: text columns parsed. Dates follow the entering terminal's format (T1 MM/DD/YY, T2 DD-Mon-YYYY);
-- a blank terminal leaves the date ambiguous when both readings are valid and differ (resolved against ERP evidence downstream).
with p as (
    select
        t.trans_id, trim(t.item_code) as legacy_code, t.trans_type, t.trans_date as trans_date_raw,
        t.entry_terminal as terminal,
        cast(try_strptime(t.trans_date, '%m/%d/%y') as date) as d_mdy,
        cast(try_strptime(t.trans_date, '%d/%m/%y') as date) as d_dmy,
        cast(try_strptime(t.trans_date, '%d-%b-%Y') as date) as d_mon,
        t.qty as qty_raw,
        try_cast(replace(trim(t.qty), ',', '') as integer) as qty,
        try_cast(replace(t.unit_cost, '$', '') as double) as unit_cost,
        t.ref_no, t.party_id, t.memo, t._file_id, t._row_num, lf.arrival as dump_date
    from {{ source('raw', 'legacy_inv_trans') }} t
    join {{ source('raw', '_load_files') }} lf on lf.file_id = t._file_id and lf.status in ('LOADED', 'RELOADED_CHANGED')
)
select *,
    case when terminal = 'T2' then d_mon when terminal = 'T1' then d_mdy
         when d_mdy is null then d_dmy when d_dmy is null then d_mdy when d_mdy = d_dmy then d_mdy end as trans_date,
    (terminal is null and d_mdy is not null and d_dmy is not null and d_mdy <> d_dmy) as date_ambiguous
from p
