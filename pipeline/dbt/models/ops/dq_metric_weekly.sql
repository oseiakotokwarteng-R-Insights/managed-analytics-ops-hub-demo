{{ config(materialized='table') }}
-- Data-quality rates by week, one series per defect family. Control limits: the median of the previous 12 weeks (robust to one bad week) +/- 5 binomial sigma.
-- A steady background rate is normal and stays quiet; a jump or collapse is what raises an alert. Rules of the road:
--   * a rate is judged only after 12 prior weeks of meaningful volume (at least 100 rows each) exist (burn-in);
--   * only settled weeks (older than 14 days) are judged, because late events and later ERP corrections are still arriving for newer ones;
--   * rates driven by the business calendar (items being superseded, new items launched) and the stock-quality shares are shown but not charted.
with m as (
    select 'wms_duplicate_delivery_rate' as metric, date_trunc('week', local_date) as week, sum(n_copies - 1) as num, sum(n_copies) as den, true as charted from {{ ref('stg_wms__event') }} group by 2
    union all select 'wms_late_arrival_rate', date_trunc('week', local_date), sum((date_diff('minute', event_ts_utc, published_ts_utc) >= 360)::int), count(*), true from {{ ref('stg_wms__event') }} group by 2
    union all select 'wms_item_not_yet_linked_rate', date_trunc('week', local_date), sum((quality_flag = 'item_linked_late')::int), count(*), false from {{ ref('fct_stock_movement') }} where source_system = 'WMS' group by 2
    union all select 'wms_receipt_item_mismatch_rate', date_trunc('week', local_date), sum((event_id in (select event_id from {{ ref('int_wms__receipt_fix') }}))::int), count(*), true from {{ ref('stg_wms__event') }} where event_type = 'RECEIVE' group by 2
    union all select 'wms_missing_ship_confirmation_rate', date_trunc('week', local_date), sum(is_inferred::int), count(*), true from {{ ref('fct_stock_movement') }} where movement_type = 'SHIPMENT' and source_system in ('WMS', 'INFERRED') group by 2
    union all select 'legacy_unparseable_quantity_rate', date_trunc('week', dump_date), sum((qty is null)::int), count(*), true from {{ ref('stg_legacy__trans') }} group by 2
    union all select 'legacy_ambiguous_date_rate', date_trunc('week', dump_date), sum(date_ambiguous::int), count(*), true from {{ ref('stg_legacy__trans') }} group by 2
    union all select 'legacy_unknown_vendor_rate', date_trunc('week', t.dump_date), sum((v.trans_id is not null)::int), count(*), true
        from {{ ref('stg_legacy__trans') }} t left join {{ ref('recon_legacy_vendor_ref') }} v on v.trans_id = t.trans_id where t.trans_type = 'RCPT' group by 2
    union all select 'erp_nonpositive_quantity_rate', date_trunc('week', cast(order_ts_utc as date)), sum((exclude_reason = 'E3_QUANTITY_NOT_POSITIVE')::int), count(*), true from {{ ref('fct_order_line') }} where not is_duplicate group by 2
    union all select 'erp_warehouse_missing_rate', date_trunc('week', cast(order_ts_utc as date)), sum(flag_wh_filled::int), count(*), true from {{ ref('fct_order_line') }} where not is_duplicate group by 2
    union all select 'erp_case_quantity_rate', date_trunc('week', cast(order_ts_utc as date)), sum(flag_uom_converted::int), count(*), true from {{ ref('fct_order_line') }} where not is_duplicate group by 2
    union all select 'erp_duplicate_line_rate', date_trunc('week', cast(order_ts_utc as date)), sum(is_duplicate::int), count(*), true from {{ ref('fct_order_line') }} group by 2
    union all select 'erp_superseded_item_rekeyed_rate', date_trunc('week', cast(order_ts_utc as date)), sum(flag_item_remapped::int), count(*), false from {{ ref('fct_order_line') }} where not is_duplicate group by 2
    union all select 'erp_changed_after_entry_rate', date_trunc('week', cast(order_ts_utc as date)), sum(flag_modified_after_entry::int), count(*), true from {{ ref('fct_order_line') }} where not is_duplicate group by 2
    union all select 'freight_reference_unmatched_rate', date_trunc('week', cast(pickup_ts_utc as date)), sum((match_status = 'REVIEW')::int), count(*), true from {{ ref('fct_shipment') }} group by 2
    union all select 'freight_delivery_time_invalid_rate', date_trunc('week', cast(pickup_ts_utc as date)), sum(flag_delivery_time_invalid::int), count(*), true from {{ ref('fct_shipment') }} group by 2
    union all select 'freight_weight_missing_rate', date_trunc('week', cast(pickup_ts_utc as date)), sum((weight_lb_reported is null)::int), count(*), true from {{ ref('fct_shipment') }} group by 2
    union all select 'freight_duplicate_charge_rate', date_trunc('week', cast(s.pickup_ts_utc as date)), sum(c.is_suspect_duplicate::int), count(*), true
        from {{ ref('fct_freight_charge') }} c join {{ ref('fct_shipment') }} s using (shipment_key) group by 2
    union all select 'count_sku_unresolved_rate', date_trunc('week', count_date), sum((sku_resolution = 'unresolved')::int), count(*), true from {{ ref('fct_count') }} group by 2
    union all select 'count_case_vs_each_suspect_rate', date_trunc('week', count_date), sum(uom_suspect::int), count(*), true from {{ ref('fct_count') }} group by 2
    union all select 'count_date_outside_month_rate', date_trunc('week', count_date), sum((not date_in_sheet_month)::int), count(*), true from {{ ref('fct_count') }} group by 2
    union all select 'receipt_quantity_variance_rate', date_trunc('week', l.received_date), sum((v.po_no is not null)::int), count(*), true
        from {{ ref('fct_po_line') }} l left join {{ ref('recon_receipt_variance') }} v on v.po_no = l.po_no and v.line_no = l.line_no where l.received_date is not null group by 2
    union all select 'stock_suspect_share', date_trunc('week', local_date), sum((confidence = 'suspect')::int), count(*), false from {{ ref('mart_stock_daily') }} group by 2
    union all select 'stock_negative_episode_share', date_trunc('week', local_date), sum(flag_negative_episode::int), count(*), false from {{ ref('mart_stock_daily') }} group by 2
),
w as (
    select *, quantile_cont(num / nullif(den, 0), 0.5) filter (where den >= 100) over p as p0, count(*) filter (where den >= 100) over p as n_prior
    from m window p as (partition by metric order by week rows between 12 preceding and 1 preceding)
)
select metric, cast(week as date) as week, num, den, num / nullif(den, 0) as rate, p0,
       (num / nullif(den, 0) - p0) / nullif(sqrt(p0 * (1 - p0) / den), 0) as z,
       cast(week as date) + 6 <= cast('{{ var("history_end") }}' as date) - 14 as is_settled,
       charted and cast(week as date) + 6 <= cast('{{ var("history_end") }}' as date) - 14
       and n_prior >= 12 and den * p0 >= 5 and den >= 100 and abs((num / nullif(den, 0) - p0) / nullif(sqrt(p0 * (1 - p0) / den), 0)) >= 5 as is_out_of_control
from w
