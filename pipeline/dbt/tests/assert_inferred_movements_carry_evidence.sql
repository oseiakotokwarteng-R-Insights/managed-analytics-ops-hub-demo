-- Every inferred movement states its rule and evidence strength.
select movement_id from {{ ref('fct_stock_movement') }} where is_inferred and (inference_rule is null or evidence_score is null or evidence_score < 0.5)
