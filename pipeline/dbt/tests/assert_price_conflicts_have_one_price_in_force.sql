-- Every price conflict has exactly one price in force (the later entry).
select vendor_name, item_no, effective_date from {{ ref('recon_price_conflicts') }}
group by 1, 2, 3 having count(*) filter (where is_price_in_force) <> 1
