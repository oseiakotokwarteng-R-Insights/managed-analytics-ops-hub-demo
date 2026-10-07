-- One row per warehouse per night of history.
select 1 from (select count(*) n from {{ ref('mart_ghost_stock_daily') }}) a,
              (select count(*) * (date_diff('day', cast('{{ var("history_start") }}' as date), cast('{{ var("history_end") }}' as date)) + 1) n from {{ ref('dim_warehouse') }}) b
where a.n <> b.n
