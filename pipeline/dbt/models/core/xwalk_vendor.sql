-- Legacy vendor ids -> ERP vendor. Exact name match for the original rows; duplicate legacy rows merge when address and phone agree
-- (strong), and go to review when only the name is similar (weak).
with l as (select * from {{ ref('stg_legacy__vendor') }}),
e as (select vendor_no, upper(name) as uname from {{ ref('stg_erp__vendor') }}),
exact as (select l.vendor_id, e.vendor_no, 'name_exact' as match_method, 1.0 as confidence from l join e on e.uname = l.vendor_name),
rest as (select * from l where vendor_id not in (select vendor_id from exact)),
strong as (
    select r.vendor_id, x.vendor_no, 'address_and_phone_match' as match_method, 0.95 as confidence
    from rest r join l o on o.address = r.address and o.phone = r.phone and o.vendor_id <> r.vendor_id
    join exact x on x.vendor_id = o.vendor_id
),
weak as (
    select r.vendor_id, e.vendor_no, 'name_similarity_only' as match_method, jaro_winkler_similarity(r.vendor_name, e.uname) as confidence,
           row_number() over (partition by r.vendor_id order by jaro_winkler_similarity(r.vendor_name, e.uname) desc) as rk
    from rest r cross join e where r.vendor_id not in (select vendor_id from strong)
)
select vendor_id as legacy_vendor_id, vendor_no, match_method, confidence, 'AUTO' as status from exact
union all select vendor_id, vendor_no, match_method, confidence, 'AUTO' from strong
union all select vendor_id, vendor_no, match_method, confidence, 'REVIEW' from weak where rk = 1
