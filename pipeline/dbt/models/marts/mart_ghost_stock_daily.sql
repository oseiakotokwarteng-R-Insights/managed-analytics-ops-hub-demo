{{ config(materialized='table') }}
-- For every warehouse and every night: how many order lines were stuck that night (7 to 60 days old, not shipped, stock said to be on hand), and over how many SKUs.
-- Lines open for more than 60 days are treated as dead (never closed in the ERP) and stop counting, so old leftovers do not pile up in the baseline.
-- The alert threshold is learned per warehouse from the first 12 months of history, before any incident: twice that warehouse's busiest night (at least 5 lines),
-- and the stuck lines must span at least 3 SKUs.
with win as (select cast('{{ var("history_start") }}' as date) as d0, cast('{{ var("history_end") }}' as date) as dend),
stuck as (
    select s.wh_code, s.item_no, s.line_value, cast(g.d as date) as as_of
    from {{ ref('mart_ghost_stock_line') }} s, win,
         unnest(generate_series(s.order_date + 7, least(coalesce(s.last_ship_date - 1, win.dend), s.order_date + 60), interval 1 day)) as g(d)
),
cnt as (select wh_code, as_of, count(*) as n_lines, count(distinct item_no) as n_skus, round(sum(line_value), 2) as stuck_value from stuck group by 1, 2),
spine as (select w.wh_code, cast(g.d as date) as as_of from {{ ref('dim_warehouse') }} w, win, unnest(generate_series(win.d0, win.dend, interval 1 day)) as g(d)),
daily as (
    select sp.wh_code, sp.as_of, coalesce(c.n_lines, 0) as n_lines, coalesce(c.n_skus, 0) as n_skus, coalesce(c.stuck_value, 0) as stuck_value
    from spine sp left join cnt c using (wh_code, as_of)
),
base as (select wh_code, greatest(5, 2 * max(n_lines)) as threshold from daily, win where as_of <= win.d0 + 365 group by 1)
select d.*, b.threshold, d.n_lines >= b.threshold and d.n_skus >= 3 as is_alert
from daily d join base b using (wh_code)
