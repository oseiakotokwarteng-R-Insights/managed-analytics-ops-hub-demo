{# WH-02 changed its bin labels on 2026-02-15 (A-12-3 -> A12-03). Normalise either shape to the old one. #}
{% macro canonical_bin(col) -%}
case
    when regexp_matches({{ col }}, '^[A-Z]-[0-9]+-[0-9]+$') then {{ col }}
    when regexp_matches({{ col }}, '^[A-Z][0-9]{2}-[0-9]{2}$')
        then substr({{ col }}, 1, 1) || '-' || cast(cast(substr({{ col }}, 2, 2) as integer) as varchar) || '-' || cast(cast(substr({{ col }}, 5, 2) as integer) as varchar)
    else {{ col }}
end
{%- endmacro %}
