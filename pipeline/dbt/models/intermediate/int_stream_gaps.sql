-- A warehouse feed that has gone quiet: from the first expected working day (Monday to Saturday, not a holiday) with no events at all, up to the build date.
-- While it lasts, that warehouse's stock estimates cannot be trusted and are marked suspect. When the feed catches up, the next build has events for those days and the flag disappears.
with last as (select wh_code, max(local_date) as last_event_date from {{ ref('stg_wms__event') }} group by 1),
open_days as (
    select cast(g.d as date) as d
    from generate_series(cast('{{ var("history_start") }}' as date), cast('{{ var("history_end") }}' as date), interval 1 day) as g(d)
    where dayofweek(cast(g.d as date)) <> 0 and cast(g.d as date) not in (select closure_date from {{ ref('closure_days') }})
),
first_missing as (select l.wh_code, min(o.d) as first_missing from last l join open_days o on o.d > l.last_event_date group by 1)
select f.wh_code, cast(g.d as date) as local_date
from first_missing f, unnest(generate_series(f.first_missing, cast('{{ var("history_end") }}' as date), interval 1 day)) as g(d)
