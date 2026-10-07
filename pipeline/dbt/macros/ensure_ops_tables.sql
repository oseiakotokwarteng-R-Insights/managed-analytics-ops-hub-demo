{# Tables written by pipeline/ops/record_dbt.py must exist before any model that reads them. #}
{% macro ensure_ops_tables() %}
    {% do run_query("create schema if not exists ops") %}
    {% do run_query("create table if not exists ops.dbt_invocation (invocation_id varchar, command varchar, generated_at timestamp, elapsed_s double, n_pass integer, n_fail integer, n_error integer, n_skip integer, n_warn integer, as_of date)") %}
    {% do run_query("alter table ops.dbt_invocation add column if not exists as_of date") %}
    {% do run_query("create table if not exists ops.dbt_test_result (invocation_id varchar, unique_id varchar, name varchar, status varchar, failures bigint, execution_time double, generated_at timestamp, message varchar)") %}
{% endmacro %}

{# Carrier B's approved layout v2 adds columns that the loader only creates when the first v2 file arrives. Models read them, so a warehouse built before that day (or replayed to an
   earlier date) must have them too, empty. The loader adds them in this order, so nothing changes where they already exist. #}
{% macro ensure_raw_layout_columns() %}
    {% do run_query("alter table raw.carrier_b_shipments add column if not exists service_level varchar") %}
    {% do run_query("alter table raw.carrier_b_shipments add column if not exists delivery_type varchar") %}
    {% do run_query("alter table raw.carrier_b_shipments add column if not exists wt_lbs varchar") %}
    {% do run_query("alter table raw.carrier_b_shipments add column if not exists dim_weight varchar") %}
{% endmacro %}
