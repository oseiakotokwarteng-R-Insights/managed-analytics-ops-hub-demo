select count_key, wh_code, sku_raw, count_date, counted_qty_raw, excluded_reason as reason_code
from {{ ref('fct_count') }} where not is_anchor
