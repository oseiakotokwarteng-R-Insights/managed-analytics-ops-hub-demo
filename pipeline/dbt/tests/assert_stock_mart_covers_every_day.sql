-- Every pair has a row for every day in the history window (plus the opening day).
select item_no, wh_code, count(*) as n_days
from {{ ref('mart_stock_daily') }} group by 1, 2
having count(*) <> date_diff('day', cast('{{ var("history_start") }}' as date) - 1, cast('{{ var("history_end") }}' as date)) + 1
