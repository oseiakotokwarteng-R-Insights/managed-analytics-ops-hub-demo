select tracking_no, charge_code, try_cast(amount as double) as amount, invoice_no, _file_id, _row_num
from {{ source('raw', 'carrier_b_charges') }}
