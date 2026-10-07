{{ config(materialized='table') }}
-- Cycle counts: the independent physical observations. Each row is repaired or excluded by explicit rules:
--   X2 typo in the SKU           -> repaired when exactly one ERP item is a single edit away, else unresolved
--   X5 date outside the sheet's month -> not used as an anchor (date cannot be trusted)
--   X3 cases counted but entered as each -> detected by comparing with the book; quantity multiplied by the case size
with s as (select *, rel_path || '|' || cast(sheet_row as varchar) as count_key from {{ ref('stg_sheets__count_row') }}),
known as (select item_no from {{ ref('dim_sku') }}),
unmatched as (select count_key, sku_raw from s where sku_raw not in (select item_no from known)),
typo as (
    select u.count_key, list_sort(list(i.item_no)) as cands, count(*) as n_cands
    from unmatched u join {{ ref('dim_sku') }} i on damerau_levenshtein(u.sku_raw, i.item_no) = 1
    group by 1
),
r as (
    select s.*,
        case when s.sku_raw in (select item_no from known) then s.sku_raw when t.n_cands = 1 then t.cands[1] end as item_no,
        case when s.sku_raw in (select item_no from known) then 'exact' when t.n_cands = 1 then 'single_edit_repair' else 'unresolved' end as sku_resolution
    from s left join typo t using (count_key)
),
d as (
    select r.*, i.case_qty,
           strftime(r.count_date, '%Y-%m') = r.file_month as date_in_sheet_month,
           r.count_date - 1 as eod_date
    from r left join {{ ref('dim_sku') }} i on i.item_no = r.item_no
),
b as (
    select d.*, bk.cum_book as book_before
    from d asof left join {{ ref('int_book_daily') }} bk
      on bk.item_no = d.item_no and bk.wh_code = d.wh_code and d.eod_date >= bk.local_date
)
select
    count_key, wh_code, item_no, sku_raw, sku_resolution, count_date, eod_date, date_in_sheet_month,
    counted_qty as counted_qty_raw, book_before, case_qty, counted_by,
    (case_qty > 1 and counted_qty > 0 and book_before > 0 and counted_qty * 2.5 < book_before
          and abs(counted_qty * case_qty - book_before) <= 0.3 * book_before + case_qty) as uom_suspect,
    case when case_qty > 1 and counted_qty > 0 and book_before > 0 and counted_qty * 2.5 < book_before
              and abs(counted_qty * case_qty - book_before) <= 0.3 * book_before + case_qty
         then counted_qty * case_qty else counted_qty end as counted_qty,
    (item_no is not null and date_in_sheet_month and counted_qty is not null) as is_anchor,
    case when item_no is null then 'sku_unresolved' when not date_in_sheet_month then 'date_outside_sheet_month' end as excluded_reason
from b
