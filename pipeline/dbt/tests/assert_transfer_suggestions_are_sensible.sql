-- A transfer is only suggested for an item that is at risk or out of stock, from a different warehouse, with a positive quantity.
select item_no, wh_code, transfer_from, transfer_qty from {{ ref('mart_stock_current') }}
where transfer_from is not null and (transfer_from = wh_code or transfer_qty <= 0 or risk not in ('at_risk', 'out_of_stock'))
