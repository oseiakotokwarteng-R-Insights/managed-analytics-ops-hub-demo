{{ config(materialized='table') }}
-- Value-format monitors: the shape of a column (not its schema) changing under our feet. For each entity the dominant pattern of the
-- last 3 days is compared with the dominant pattern of the 28 days before; a clean switch is drift.
with ev as (
    select 'wms.bin' as monitor, e.warehouse as entity, lf.arrival as d,
           case when regexp_matches(e.bin, '^[A-Z]-[0-9]+-[0-9]+$') then 'A-12-3'
                when regexp_matches(e.bin, '^[A-Z][0-9]{2}-[0-9]{2}$') then 'A12-03' else 'other' end as pattern
    from {{ source('raw', 'wms_events') }} e join {{ source('raw', '_load_files') }} lf on lf.file_id = e._file_id
    union all
    select 'carrier_a.shipper_ref', 'CARRIER_A', lf.arrival,
           case when regexp_matches(s.shipper_ref, '^SO-[0-9]{6}$') then 'SO-nnnnnn' when regexp_matches(s.shipper_ref, '^PO-[0-9]{6}$') then 'PO-nnnnnn' else 'other' end
    from {{ source('raw', 'carrier_a_shipments') }} s join {{ source('raw', '_load_files') }} lf on lf.file_id = s._file_id
),
daily as (select monitor, entity, d, pattern, count(*) as n from ev group by 1, 2, 3, 4),
ent as (select monitor, entity, min(d) as d0 from daily group by 1, 2),
spine as (select e.monitor, e.entity, cast(g.d as date) as as_of from ent e cross join generate_series(e.d0 + 31, cast('{{ var("history_end") }}' as date), interval 1 day) as g(d)),
roll as (
    select sp.monitor, sp.entity, sp.as_of, p.pattern,
           sum(p.n) filter (where p.d > sp.as_of - 3) as n_recent, sum(p.n) filter (where p.d <= sp.as_of - 3) as n_prior
    from spine sp join daily p on p.monitor = sp.monitor and p.entity = sp.entity and p.d > sp.as_of - 31 and p.d <= sp.as_of
    group by 1, 2, 3, 4
),
tot as (select monitor, entity, as_of, sum(n_recent) as t_recent, sum(n_prior) as t_prior from roll group by 1, 2, 3),
ranked as (
    select r.*, r.n_recent / nullif(t.t_recent, 0) as share_recent, r.n_prior / nullif(t.t_prior, 0) as share_prior,
           row_number() over (partition by r.monitor, r.entity, r.as_of order by coalesce(r.n_recent, 0) desc) as rk_recent,
           row_number() over (partition by r.monitor, r.entity, r.as_of order by coalesce(r.n_prior, 0) desc) as rk_prior
    from roll r join tot t using (monitor, entity, as_of)
),
rec as (select monitor, entity, as_of, pattern as recent_pattern, share_recent from ranked where rk_recent = 1),
pri as (select monitor, entity, as_of, pattern as prior_pattern, share_prior from ranked where rk_prior = 1)
select rec.monitor, rec.entity, rec.as_of, rec.recent_pattern, rec.share_recent, pri.prior_pattern, pri.share_prior,
       (rec.recent_pattern <> pri.prior_pattern and rec.share_recent >= 0.8 and pri.share_prior >= 0.8) as is_drift
from rec join pri using (monitor, entity, as_of)
