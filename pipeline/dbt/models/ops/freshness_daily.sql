{{ config(materialized='table') }}
-- For every stream and every night: how old is the newest data that had been loaded by then, against what the stream's owner promises.
-- A file that arrived but was held (schema drift) does not count as fresh until it is released.
with first_seen as (select stream, min(arrival) as d0 from {{ ref('ops_file_arrival') }} group by 1),
cfg as (select * from {{ ref('monitor_streams') }}),
spine as (
    select f.stream, cast(g.d as date) as as_of
    from first_seen f cross join generate_series(f.d0, cast('{{ var("history_end") }}' as date), interval 1 day) as g(d)
),
daily as (select stream, loaded_as_of as as_of, max(arrival) as max_arrival from {{ ref('ops_file_arrival') }} group by 1, 2),
j as (select sp.stream, sp.as_of, d.max_arrival from spine sp left join daily d using (stream, as_of)),
c as (select *, max(max_arrival) over (partition by stream order by as_of rows between unbounded preceding and current row) as last_arrival from j)
select c.stream, c.as_of, c.last_arrival, date_diff('day', c.last_arrival, c.as_of) as days_since_last_arrival,
       cfg.max_expected_gap_days, cfg.critical, date_diff('day', c.last_arrival, c.as_of) > cfg.max_expected_gap_days as is_late
from c join cfg using (stream)
