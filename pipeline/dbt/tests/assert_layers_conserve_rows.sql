-- Nothing may disappear between layers without a recorded reason (see ops.layer_reconciliation).
select * from {{ ref('layer_reconciliation') }} where not ok
