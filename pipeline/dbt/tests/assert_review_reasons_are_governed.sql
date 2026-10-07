-- Every row routed to a human carries a reason code that is in the registry with an owner and a suggested action.
select source_system, source_key, reason_code from {{ ref('review_queue') }}
where defect_class is null or owner_role is null or suggested_action is null or severity is null
