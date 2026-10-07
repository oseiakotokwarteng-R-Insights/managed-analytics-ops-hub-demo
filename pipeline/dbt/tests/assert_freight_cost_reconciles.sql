-- Every dollar of carrier charges is in the shipment mart, either as cost or as a suspected duplicate.
select round(sum(amount), 2) as charges, (select round(sum(cost + duplicate_cost), 2) from {{ ref('mart_freight_shipment') }}) as in_mart
from {{ ref('fct_freight_charge') }}
having abs(sum(amount) - (select sum(cost + duplicate_cost) from {{ ref('mart_freight_shipment') }})) > 0.5
