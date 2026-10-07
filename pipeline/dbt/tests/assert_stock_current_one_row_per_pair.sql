-- One current-stock row per item and warehouse, and it covers every pair the stock mart covers on the last day.
select 'duplicate' as problem, item_no, wh_code from {{ ref('mart_stock_current') }} group by 1, 2, 3 having count(*) > 1
union all
select 'missing', m.item_no, m.wh_code from {{ ref('mart_stock_daily') }} m
where m.local_date = cast('{{ var("history_end") }}' as date)
  and not exists (select 1 from {{ ref('mart_stock_current') }} c where c.item_no = m.item_no and c.wh_code = m.wh_code)
