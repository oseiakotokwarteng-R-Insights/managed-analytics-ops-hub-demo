select bol_no, c.line_id, c.code as charge_code, c.amount
from (
    select bol_no, unnest(from_json(charges_json, '[{"line_id":"VARCHAR","code":"VARCHAR","amount":"DOUBLE"}]')) as c
    from {{ ref('int_carrier_a__latest') }}
)
