select 1 from (select count(*) n from {{ ref('mart_inbound_open') }}) a, (select count(*) n from {{ ref('fct_po_line') }} where received_date is null) b where a.n <> b.n
