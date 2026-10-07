-- The systems' own count adjustments are tagged so the physical estimate can exclude them (the count itself re-anchors).
select movement_id from {{ ref('fct_stock_movement') }} where movement_type = 'COUNT_ADJUSTMENT' and not is_count_adjustment
