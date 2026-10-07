{{ config(materialized='table') }}
-- The systems' own book quantity (everything recorded plus inferred movements), cumulative by item, warehouse and day.
select item_no, wh_code, local_date,
       sum(sum(qty_delta)) over (partition by item_no, wh_code order by local_date) as cum_book
from {{ ref('fct_stock_movement') }}
group by item_no, wh_code, local_date
