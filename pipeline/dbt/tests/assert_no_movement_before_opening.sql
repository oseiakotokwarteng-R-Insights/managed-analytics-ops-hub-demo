-- Nothing may be dated before the opening-balance day: the opening balance already contains all earlier history.
select movement_id from {{ ref('fct_stock_movement') }} where local_date < cast('{{ var("history_start") }}' as date) - 1
