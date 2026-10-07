{{ config(materialized='table') }}
-- Order lines the records say should have shipped at once but did not: the estimated stock on the order date covered the quantity, yet the line shipped
-- more than 7 days later (or has not shipped). A few of these are ordinary delays; a cluster at one warehouse means the stock on the book is not really there.
select l.order_no, l.line_no, l.item_no, l.wh_code, cast(l.order_ts_utc as date) as order_date, l.last_ship_date, l.status,
       l.qty_ordered_units, l.qty_shipped_units, l.unit_price, l.qty_ordered_units * l.unit_price as line_value,
       m.est_on_hand as est_on_hand_at_order, m.book_recorded_qty as book_at_order,
       date_diff('day', cast(l.order_ts_utc as date), coalesce(l.last_ship_date, cast('{{ var("history_end") }}' as date))) as days_open
from {{ ref('fct_order_line') }} l
join {{ ref('mart_stock_daily') }} m on m.item_no = l.item_no and m.wh_code = l.wh_code and m.local_date = cast(l.order_ts_utc as date)
where not l.is_duplicate and l.exclude_reason is null
  and m.est_on_hand >= l.qty_ordered_units
  and (l.last_ship_date is null or date_diff('day', cast(l.order_ts_utc as date), l.last_ship_date) > 7)
