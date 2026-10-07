{{ config(materialized='table') }}
-- Estimated physical stock by item, warehouse and day.
--   book_recorded_qty  what the source systems recorded, exactly as recorded (no corrections, no inference): the baseline to beat.
--   book_qty           the ledger after corrections and evidence-based inference, including the systems' own count adjustments.
--   est_on_hand        physical estimate: opening balance + movements (excluding the systems' count adjustments, which re-state a count),
--                      re-anchored to the counted quantity on each valid count (counts observe the end of the previous day).
--   flags              retro_variance: a later count showed this estimate was off; input_gap: a movement in the window could not be used;
--                      stream_stale: the warehouse's feed has been silent on working days up to the build date;
--                      negative_episode: the estimate or the book went below zero and has not been re-anchored since.
--   confidence         suspect = any flag; verified = counted within 90 days; carried = otherwise (recorded movements carried forward).
with pairs as (
    select distinct item_no, wh_code from {{ ref('fct_stock_movement') }}
    union select distinct recorded_item_no, wh_code from {{ ref('fct_stock_movement') }}
    union select distinct item_no, wh_code from {{ ref('fct_count') }} where is_anchor
),
spine as (
    select p.item_no, p.wh_code, cast(g.d as date) as local_date
    from pairs p cross join generate_series(cast('{{ var("history_start") }}' as date) - 1, cast('{{ var("history_end") }}' as date), interval 1 day) as g(d)
),
net as (
    select item_no, wh_code, local_date, sum(qty_delta) as net_all,
           sum(case when is_count_adjustment then 0 else qty_delta end) as net_phys
    from {{ ref('fct_stock_movement') }} group by 1, 2, 3
),
net_rec as (
    select recorded_item_no as item_no, wh_code, local_date, sum(qty_delta) as net_recorded
    from {{ ref('fct_stock_movement') }} where not is_inferred group by 1, 2, 3
),
anch as (
    select item_no, wh_code, eod_date as local_date, max(counted_qty) as anchor_qty
    from {{ ref('fct_count') }} where is_anchor group by 1, 2, 3
),
gaps as (select item_no, wh_code, local_date, 1 as has_gap from {{ ref('int_input_gaps') }} group by 1, 2, 3),
j as (
    select s.*, coalesce(n.net_all, 0) as net_all, coalesce(n.net_phys, 0) as net_phys, coalesce(r.net_recorded, 0) as net_recorded,
           a.anchor_qty, coalesce(g.has_gap, 0) as has_gap
    from spine s
    left join net n using (item_no, wh_code, local_date)
    left join net_rec r using (item_no, wh_code, local_date)
    left join anch a using (item_no, wh_code, local_date)
    left join gaps g using (item_no, wh_code, local_date)
),
c as (
    select *,
        sum(net_all) over w as book_qty,
        sum(net_recorded) over w as book_recorded_qty,
        sum(net_phys) over w as cum_phys,
        sum(case when anchor_qty is not null then 1 else 0 end) over w as seg
    from j window w as (partition by item_no, wh_code order by local_date rows between unbounded preceding and current row)
),
o as (select *, case when anchor_qty is not null then anchor_qty - cum_phys end as off_here from c),
f as (
    select *,
        coalesce(last_value(off_here ignore nulls) over w, 0) as offset_cur,
        first_value(off_here ignore nulls) over (partition by item_no, wh_code order by local_date rows between current row and unbounded following) as offset_next,
        last_value(case when anchor_qty is not null then local_date end ignore nulls) over w as last_anchor_date,
        max(has_gap) over (partition by item_no, wh_code, seg order by local_date rows between unbounded preceding and current row) as gap_in_segment
    from o window w as (partition by item_no, wh_code order by local_date rows between unbounded preceding and current row)
),
g2 as (
    select *, cum_phys + offset_cur as est_on_hand,
           max(case when book_qty < 0 or cum_phys + offset_cur < 0 then 1 else 0 end)
               over (partition by item_no, wh_code, seg order by local_date rows between unbounded preceding and current row) as neg_in_segment
    from f
)
select
    g2.item_no, g2.wh_code, g2.local_date, book_recorded_qty, book_qty, est_on_hand,
    last_anchor_date, date_diff('day', last_anchor_date, g2.local_date) as days_since_anchor,
    coalesce(offset_next is not null and offset_next <> offset_cur, false) as flag_retro_variance,
    gap_in_segment = 1 as flag_input_gap,
    neg_in_segment = 1 as flag_negative_episode,
    sg.wh_code is not null as flag_stream_stale,
    case when coalesce(offset_next is not null and offset_next <> offset_cur, false) or gap_in_segment = 1 or neg_in_segment = 1 or sg.wh_code is not null then 'suspect'
         when last_anchor_date is not null and date_diff('day', last_anchor_date, g2.local_date) <= 90 then 'verified'
         else 'carried' end as confidence
from g2 left join {{ ref('int_stream_gaps') }} sg on sg.wh_code = g2.wh_code and sg.local_date = g2.local_date
