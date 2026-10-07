{{ config(materialized='table') }}
-- Every alert from every source in one log. A failed model test is dated to the simulated night of the build that failed and clears on the night the next build passes it. opened_as_of is the night it was raised; resolved_as_of is the night it cleared (null = still open).
with hist_end as (select cast('{{ var("history_end") }}' as date) as d),
late as (
    select stream, as_of, days_since_last_arrival, max_expected_gap_days, critical,
           as_of - cast(row_number() over (partition by stream order by as_of) as integer) as grp
    from {{ ref('freshness_daily') }} where is_late
),
late_isl as (
    select stream, min(as_of) as opened, max(as_of) + 1 as closed, max(days_since_last_arrival) as worst, any_value(max_expected_gap_days) as gap, bool_or(critical) as crit
    from late group by stream, grp
),
drift as (
    select monitor, entity, as_of, recent_pattern, prior_pattern, as_of - cast(row_number() over (partition by monitor, entity order by as_of) as integer) as grp
    from {{ ref('format_drift_daily') }} where is_drift
),
drift_isl as (select monitor, entity, min(as_of) as opened, max(as_of) + 1 as closed, any_value(prior_pattern) as p0, any_value(recent_pattern) as p1 from drift group by monitor, entity, grp),
test_runs as (select invocation_id, as_of, row_number() over (order by as_of, generated_at) as rn from {{ source('ops_raw', 'dbt_invocation') }} where command = 'test'),
test_fail as (
    select r.name, t.rn, t.as_of, r.failures, t.rn - row_number() over (partition by r.name order by t.rn) as grp
    from {{ source('ops_raw', 'dbt_test_result') }} r join test_runs t using (invocation_id)
    where r.status in ('fail', 'error') and r.unique_id like 'test.%'
),
test_isl as (select name, grp, min(as_of) as opened, max(rn) as last_rn, max(failures) as failures from test_fail group by name, grp),
u as (
    select 'load_or_schema' as alert_type, severity, table_name as entity, code as alert_code, as_of as opened_as_of, resolved_as_of, message from {{ source('raw', '_alerts') }}
    union all
    select 'stream_stale', case when crit then 'ERROR' else 'WARNING' end, stream, 'STREAM_STALE', opened, case when closed > (select d from hist_end) then null else closed end,
           stream || ' delivered nothing new for ' || cast(worst as varchar) || ' days (the stream owner promises at most ' || cast(gap as varchar) || ')' from late_isl
    union all
    select 'volume_anomaly', 'WARNING', stream, case when ratio > 1 then 'VOLUME_SPIKE' else 'VOLUME_DROP' end, as_of, as_of + 1,
           stream || ' delivered ' || cast(cast(n_rows as integer) as varchar) || ' rows on ' || cast(arrival as varchar) || ' against a usual ' || cast(cast(baseline as integer) as varchar)
    from {{ ref('volume_daily') }} where is_anomaly
    union all
    select 'duplicate_file', 'WARNING', stream, 'FILE_RESENT', as_of, as_of + 1, rel_path || ' is byte-for-byte identical to ' || duplicate_of from {{ ref('duplicate_file_daily') }}
    union all
    select 'value_format_drift', 'WARNING', monitor || ' ' || entity, 'VALUE_FORMAT_DRIFT', opened, case when closed > (select d from hist_end) then null else closed end,
           monitor || ' for ' || entity || ' switched from pattern ' || p0 || ' to ' || p1 from drift_isl
    union all
    select 'dq_rate_out_of_control', 'WARNING', metric, 'DQ_RATE_OUT_OF_CONTROL', week + 6, week + 7,
           metric || ' was ' || cast(round(100 * rate, 2) as varchar) || '% in the week of ' || cast(week as varchar) || ' against ' || cast(round(100 * p0, 2) as varchar) || '% before'
    from {{ ref('dq_metric_weekly') }} where is_out_of_control
    union all
    select 'model_test_failed', 'ERROR', name, 'DBT_TEST_FAILED', opened, (select t.as_of from test_runs t where t.rn = i.last_rn + 1), name || ' failed with ' || cast(failures as varchar) || ' rows'
    from test_isl i
)
select row_number() over (order by opened_as_of, alert_type, entity) as alert_id, u.* from u
