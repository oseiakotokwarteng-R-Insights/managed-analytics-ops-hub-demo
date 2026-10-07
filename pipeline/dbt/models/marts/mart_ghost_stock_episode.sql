{{ config(materialized='table') }}
-- Phantom-stock episodes: runs of alert nights at one warehouse (gaps of up to 3 quiet nights are bridged). For each episode:
--   alert_date            the night the alert fired;
--   est_start             when the trouble most likely began. Among the SKUs with 3 or more stuck lines, each SKU's start is its first stuck line that is followed by another
--                         stuck line (isolated late orders are ordinary); the episode start is the third earliest of those, so one or two coincidences cannot move it;
--   affected SKUs, stuck order lines and their value, and the value the book still claims for those SKUs on the alert date;
--   first_confirming_count the date by which counts had found at least 5 of those SKUs far below the book (counted at or under 20% of the book quantity).
with win as (select cast('{{ var("history_end") }}' as date) as dend),
a as (
    select wh_code, as_of, lag(as_of) over (partition by wh_code order by as_of) as prev
    from {{ ref('mart_ghost_stock_daily') }} where is_alert
),
isl as (
    select wh_code, as_of, sum((prev is null or date_diff('day', prev, as_of) > 4)::int) over (partition by wh_code order by as_of) as ep from a
),
ep as (
    select wh_code, ep as episode, min(as_of) as alert_date, max(as_of) as last_alert_date from isl group by 1, 2
),
lines as (
    select e.wh_code, e.episode, e.alert_date, e.last_alert_date, l.*
    from ep e join {{ ref('mart_ghost_stock_line') }} l
      on l.wh_code = e.wh_code and l.order_date between e.alert_date - 45 and e.last_alert_date - 7 and coalesce(l.last_ship_date, (select dend from win)) >= e.alert_date
),
persist as (select wh_code, episode, item_no from lines group by 1, 2, 3 having count(*) >= 3),
cl as (select l.* from lines l join persist p using (wh_code, episode, item_no)),
-- every valid order line of the cluster SKUs in the window, stuck or not, so "followed by another stuck line" can be judged
allv as (
    select e.wh_code, e.episode, o.item_no, o.order_no, o.line_no, cast(o.order_ts_utc as date) as order_date,
           (g.order_no is not null) as stuck
    from ep e
    join persist p on p.wh_code = e.wh_code and p.episode = e.episode
    join {{ ref('fct_order_line') }} o on o.wh_code = e.wh_code and o.item_no = p.item_no and not o.is_duplicate and o.exclude_reason is null
         and cast(o.order_ts_utc as date) between e.alert_date - 45 and e.last_alert_date - 7
    left join {{ ref('mart_ghost_stock_line') }} g on g.order_no = o.order_no and g.line_no = o.line_no
),
chain as (
    select *, lead(stuck) over (partition by wh_code, episode, item_no order by order_date, order_no, line_no) as next_stuck from allv
),
sku_start as (
    select wh_code, episode, item_no, min(order_date) as start_date from chain where stuck and coalesce(next_stuck, false) group by 1, 2, 3
),
st as (
    select wh_code, episode, list_sort(list(start_date))[least(3, count(*))] as est_start from sku_start group by 1, 2
),
agg as (
    select wh_code, episode, any_value(alert_date) as alert_date, any_value(last_alert_date) as last_alert_date,
           count(distinct item_no) as affected_skus, count(*) as stuck_order_lines, round(sum(line_value), 2) as stuck_order_value
    from cl group by 1, 2
),
bk as (
    select a.wh_code, a.episode, round(sum(greatest(m.est_on_hand, 0) * s.std_cost), 2) as book_value_at_risk
    from agg a join persist i using (wh_code, episode)
    join {{ ref('mart_stock_daily') }} m on m.item_no = i.item_no and m.wh_code = i.wh_code and m.local_date = a.alert_date
    join {{ ref('dim_sku') }} s on s.item_no = i.item_no group by 1, 2
),
conf as (
    select i.wh_code, i.episode, i.item_no, min(c.count_date) as confirmed_on
    from persist i join st using (wh_code, episode)
    join {{ ref('fct_count') }} c on c.item_no = i.item_no and c.wh_code = i.wh_code and c.is_anchor and c.count_date >= st.est_start
         and c.book_before >= 5 and c.counted_qty <= 0.2 * c.book_before
    group by 1, 2, 3
),
cc as (
    select wh_code, episode, case when count(*) >= 5 then list_sort(list(confirmed_on))[5] end as first_confirming_count from conf group by 1, 2
)
select a.wh_code, w.name as wh_name, a.alert_date, a.last_alert_date, st.est_start, a.affected_skus, a.stuck_order_lines, a.stuck_order_value, b.book_value_at_risk,
       c.first_confirming_count, date_diff('day', a.alert_date, c.first_confirming_count) as alert_days_before_count
from agg a join {{ ref('dim_warehouse') }} w using (wh_code) left join st using (wh_code, episode) left join bk b using (wh_code, episode) left join cc c using (wh_code, episode)
