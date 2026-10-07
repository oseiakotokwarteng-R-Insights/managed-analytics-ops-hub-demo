select vendor_id, vendor_name, address, city_state, phone, terms, status
from {{ source('raw', 'legacy_vendor') }}
