-- The latest night, with every alert that is still open.
select h.as_of, h.health, h.run_status, h.open_errors, h.open_warnings, a.alert_type, a.severity, a.entity, a.opened_as_of, a.message
from (select * from {{ ref('pipeline_health_daily') }} order by as_of desc limit 1) h
left join {{ ref('alerts_unified') }} a on a.resolved_as_of is null and a.severity in ('ERROR', 'WARNING')
