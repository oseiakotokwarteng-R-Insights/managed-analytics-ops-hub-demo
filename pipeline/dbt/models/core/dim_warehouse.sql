select
    w.wh_code, w.name, w.city, w.timezone,
    case when exists (select 1 from {{ ref('stg_wms__event') }} e where e.wh_code = w.wh_code) then 'WMS' else 'LEGACY' end as system_of_record
from {{ ref('stg_erp__warehouse') }} w
