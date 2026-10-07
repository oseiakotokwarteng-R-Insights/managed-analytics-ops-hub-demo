{{ config(materialized='table') }}
-- One row per night: did the run work, and is anything wrong anywhere? Red = an error-level alert is open; amber = warnings only; green = clean.
with runs as (select as_of, status, files_loaded, files_held, files_failed, files_released, rows_loaded, duration_s from {{ source('raw', '_load_runs') }}),
open_alerts as (
    select r.as_of, a.severity, a.alert_type, a.entity
    from runs r join {{ ref('alerts_unified') }} a on a.opened_as_of <= r.as_of and (a.resolved_as_of is null or r.as_of < a.resolved_as_of)
),
agg as (
    select as_of,
           count(*) filter (where severity = 'ERROR') as open_errors,
           count(*) filter (where severity = 'WARNING') as open_warnings,
           count(*) filter (where severity = 'INFO') as open_info,
           string_agg(alert_type || ': ' || entity, '; ' order by alert_type, entity) filter (where severity in ('ERROR', 'WARNING')) as issues
    from open_alerts group by 1
)
select r.as_of, r.status as run_status, r.files_loaded, r.files_held, r.files_failed, r.files_released, r.rows_loaded, round(r.duration_s, 1) as duration_s,
       coalesce(a.open_errors, 0) as open_errors, coalesce(a.open_warnings, 0) as open_warnings, coalesce(a.open_info, 0) as open_info,
       case when coalesce(a.open_errors, 0) > 0 or r.files_failed > 0 then 'red' when coalesce(a.open_warnings, 0) > 0 then 'amber' else 'green' end as health,
       a.issues
from runs r left join agg a using (as_of)
