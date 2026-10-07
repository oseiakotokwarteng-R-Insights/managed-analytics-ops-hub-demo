-- One estimate per item, warehouse and day.
select item_no, wh_code, local_date, count(*) as n from {{ ref('mart_stock_daily') }} group by 1, 2, 3 having count(*) > 1
