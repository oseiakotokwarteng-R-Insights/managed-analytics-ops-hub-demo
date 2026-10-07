-- Documentation of every automated check: what it watches, how it decides, and what it raises.
select * from (values
    ('schema_drift', 'every file, every night', 'columns match an approved contract version', 'file held, ERROR until a contract is approved', 'ingestion engine'),
    ('stream_freshness', 'each of 16 source streams, every night', 'newest loaded data no older than the stream owner promises', 'ERROR (stock-critical stream) or WARNING', 'ops.freshness_daily'),
    ('volume_anomaly', 'each stream, every day', 'rows within 0.25x-3x of the same weekday over the previous 8 weeks; holiday-weekend quiet excluded', 'WARNING', 'ops.volume_daily'),
    ('duplicate_file', 'every file', 'no two differently named files carry identical bytes', 'WARNING', 'ops.duplicate_file_daily'),
    ('value_format_drift', 'WMS bin labels per warehouse; carrier reference shape', 'dominant pattern of the last 3 days equals that of the previous 28', 'WARNING', 'ops.format_drift_daily'),
    ('dq_rate_control', '20 charted defect-family rates (24 tracked), weekly', 'rate within 5 binomial sigma of the previous 12 weeks', 'WARNING', 'ops.dq_metric_weekly'),
    ('layer_conservation', '9 layer-to-layer row counts', 'rows in = rows out + rows set aside with a reason', 'dbt test failure (ERROR)', 'ops.layer_reconciliation'),
    ('model_tests', 'keys, not-null, accepted values, relationships, coverage, evidence', 'dbt tests', 'ERROR', 'dbt test'),
    ('reason_code_governance', 'every quarantine or review row', 'reason code exists in the registry with an owner and action', 'dbt test failure (ERROR)', 'ref.dq_reason_codes')
) as t(check_name, scope, rule, raises, implemented_in)
