{{ config(materialized='table') }}
-- Rows arriving per stream per day against the median of the same weekday over the previous 8 weeks.
-- A quiet spell around a public holiday (the day before to three days after) is expected and is not flagged; a surge never is.
with a as (
    select stream, arrival, min(loaded_as_of) as as_of, sum(rows_loaded) as n_rows, count(*) as n_files
    from {{ ref('ops_file_arrival') }} group by 1, 2
),
b as (
    select a.*,
           quantile_cont(n_rows, 0.5) over w as baseline,
           count(n_rows) over w as n_baseline
    from a window w as (partition by stream, dayofweek(arrival) order by arrival rows between 8 preceding and 1 preceding)
)
select b.*, b.n_rows / nullif(b.baseline, 0) as ratio,
       (b.n_baseline >= 4 and b.baseline >= 20 and (
            b.n_rows / b.baseline > 3.0
            or (b.n_rows / b.baseline < 0.25 and not exists (select 1 from {{ ref('closure_days') }} c where b.arrival between c.closure_date - 1 and c.closure_date + 3))
       )) as is_anomaly
from b
