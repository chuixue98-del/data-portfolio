{{
    config(
        materialized = 'incremental',
        unique_key = 'event_id',
        incremental_strategy = 'delete+insert'
    )
}}

-- Event history. On each run only events loaded since the last run are processed.
select
    event_id,
    shipment_id,
    status,
    event_at,
    carrier_code,
    _loaded_at
from {{ ref('stg_tracking_events') }}

{% if is_incremental() %}
where _loaded_at > (select max(_loaded_at) from {{ this }})
{% endif %}
