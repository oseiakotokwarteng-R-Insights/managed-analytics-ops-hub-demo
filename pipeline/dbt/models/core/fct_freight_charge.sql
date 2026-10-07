-- F7: a charge line repeated with the same code and amount on the same shipment is flagged as a suspected duplicate bill (recoverable).
with a as (
    select 'CARRIER_A' as carrier, bol_no as shipment_key, line_id, charge_code, amount from {{ ref('int_carrier_a__charge') }}
), b as (
    select 'CARRIER_B', tracking_no, 'B-' || cast(_file_id as varchar) || '-' || cast(_row_num as varchar), charge_code, amount from {{ ref('stg_carrier_b__charge') }}
), u as (select * from a union all select * from b)
select u.*,
       row_number() over (partition by shipment_key, charge_code, amount order by line_id) > 1 as is_suspect_duplicate
from u
