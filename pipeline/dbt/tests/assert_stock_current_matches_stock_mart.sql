-- The headline estimate on the dashboard is the stock mart's estimate for the same day, unchanged.
select c.item_no, c.wh_code from {{ ref('mart_stock_current') }} c
join {{ ref('mart_stock_daily') }} m on m.item_no = c.item_no and m.wh_code = c.wh_code and m.local_date = c.as_of
where c.est_on_hand <> m.est_on_hand or c.confidence <> m.confidence
